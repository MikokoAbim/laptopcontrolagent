import asyncio
import json
import os
import uuid
from typing import Any, Optional

from dotenv import load_dotenv
from contextlib import AsyncExitStack
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import InMemorySaver

from mcp_client import SimpleMCPClient
from mcp import types

from langchain_core.tools import StructuredTool
from pydantic import create_model

load_dotenv()


class MCPChatApp:
    def __init__(self, servers: list[dict]):
        # self.client = SimpleMCPClient(command=server_command, args=server_args)
        self.clients = [
            SimpleMCPClient(command=s["command"], args=s["server_args"]) for s in servers
        ]

        self.mcp_tools: list[types.Tool] = []
        self.langchain_tools = []

        self.llm = ChatOllama(
            model="qwen2.5:7b",
            temperature=0.7,
            num_ctx=4096,  # ← increase context window
        )

        # This acts as a dictrionary of IDs containing the conversation history
        # Because this is passed to create agent, the agent will automatically
        # load and save history on every ainvoke call using the thread_ID provided
        self.checkpointer = InMemorySaver()

        # Generate a single ID for this entire session
        # Every message sent and received will be stored under this ID in the checkpointer (InMemorySaver)
        self.thread_id = str(uuid.uuid4())
        self.agent = None

    def _wrap_mcp_tool(self, client: SimpleMCPClient, mcp_tool: types.Tool):
        """
        Wrap one MCP tool as a LangChain tool.

        This uses a single `arguments` dict so we do not need to hand-build a
        separate Pydantic schema for every MCP schema shape.
        """
        description = mcp_tool.description or f"Execute {mcp_tool.name}"

        # Check if the tool has an InputSchema and add it to the description of the function
        # this inputschema is automatically gotten from the function signature
        # of functions within the server.py with the @mcp.tool annotation

        # E.g
        # description = "Function that writes to file
        #       Input schema: {filepath: string, contents: string}"
        if getattr(mcp_tool, "inputSchema", None):
            description += (
                "\nInput schema: "
                # convert the dictionary which mcp_tool.inputSchema is to json
                + json.dumps(mcp_tool.inputSchema, ensure_ascii=False)
            )

        # build a pydantic model from the real schema fields
        # so LangChain knows exactly how to map args into the function
        properties = mcp_tool.inputSchema.get("properties", {}) if getattr(mcp_tool, "inputSchema", None) else {}
        fields = {name: (Optional[Any], None) for name in properties}
        DynamicSchema = create_model(f"{mcp_tool.name}Input", **fields)

        tool_name = mcp_tool.name  # captured in closure

        async def run_mcp_tool(**kwargs) -> str:
            # filter out None values so optional fields dont get sent to the server
            args = {k: v for k, v in kwargs.items() if v is not None}
            result = await client.call_tool(tool_name, args)
            if getattr(result, "content", None):
                return str(result.content)
            return "Tool executed successfully"

        return StructuredTool.from_function(
            coroutine=run_mcp_tool,
            name=tool_name,
            description=description,
            args_schema=DynamicSchema,
        )
    
    async def chat_loop(self):
        print("Chat started (Gemma 4 or qwen2.5 local)\n")

        while True:
            try:
                user_input = await asyncio.to_thread(input, "You> ")
                user_input = user_input.strip()

                if not user_input:
                    continue

                if user_input.lower() in ["/exit", "/quit"]:
                    print("Goodbye!")
                    break

                if user_input.lower() == "/clear":
                    self.thread_id = str(uuid.uuid4())
                    print("Conversation cleared.\n")
                    continue

                # ainvoke()
                # → model call with user input
                # → tool call detected
                # → tool executed
                # → model called again
                # → return final state
                result = await self.agent.ainvoke(
                    {"messages": [{"role": "user", "content": user_input}]},

                    # tell the checkpointer which conversation to load as extra context for this message
                    # We only pass the current thread_id here so past sessions after /clear arent included 
                    # in the LLM context right now
                    # but they still exist in the checkpointer history
                    {"configurable": {"thread_id": self.thread_id}},
                )

                assistant_message = result["messages"][-1].content
                print(f"\n {result} \n")
                print(f"\nAssistant> {assistant_message}\n")

            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {e}\n")

    async def start(self):
        print("=" * 60)
        print("MCP Chat App (LangChain + Ollama + Gemma 4 e2b or qwen2.5:7b)")
        print("=" * 60)

        try:
            # open all clients at once using AsyncExitStack

            async with AsyncExitStack() as stack:
                connected_clients = []
                for client in self.clients:
                    connected = await stack.enter_async_context(client)
                    connected_clients.append(connected)

                print("\nAll clients are Connected! Available tools:")

                for connected_client in connected_clients:
                    mcp_tools = await connected_client.list_tools()

                    for tool_def in mcp_tools:
                        print(f"  • {tool_def.name}: {tool_def.description}")

                        # every tool is givena langchain tool signature with their tool name, description(description, inputschema)
                        # [
                        # @tool(write_doc, 
                        # "Function that writes to file Input schema: {filepath: string, contents: string}")
                        # run_mcp_tool(arguements: dict[str, Any]), ]

                        # Concise exmaple
                        # langchain_tools = [
                        #   @tool("read_doc", description="...schema...")  → run_mcp_tool
                        #   @tool("write_doc", description="...schema...") → run_mcp_tool
                        # ]
                        self.langchain_tools.append(self._wrap_mcp_tool(connected_client, tool_def))
                            

                self.agent = create_agent(
                    model=self.llm,
                    tools=self.langchain_tools,
                    system_prompt=(
                        "You are a helpful desktop automation assistant. Use MCP tools when relevant. "

                        "IMPORTANT RULES: "
                        "NEVER batch multiple tool calls together. "
                        "Always wait for each tool to return before calling the next one. "
                        "One tool call at a time only."

                        "If the user asks anything about their screen, current window, buttons, or UI elements "
                        "ALWAYS call get_screen_elements immediately. Never ask for clarification. Just call the tool. "
                        "Never summarize or cut the element list short when reporting to the user. "

                        "To type into any search box or input field, always click the Edit element first. "
                        "Edit elements are text input fields. Always prefer clicking an Edit over a Button when searching. "

                        "When using focus_application or get_screen_elements, use the exact app name the user provides. "
                        "Never add words like 'Messenger', 'Desktop', 'App' to the app name. "

                        "For desktop automation tasks follow this exact order: "
                        "1. focus_application to bring it to the front "
                        "2. get_screen_elements to get coordinates "
                        "3. mouse_click using those coordinates "
                        "4. get_screen_elements again after every click to see the updated screen before continuing "

                        "For typing: "
                        "Always mouse_click the input field first to focus it, then call type_text. "
                        "Never call type_text without clicking the field first. "

                        "For web searches: "
                        "Use web_search only for questions about facts, news, or information from the internet. "
                    ),
                    checkpointer=self.checkpointer,  # ← "I want memory, here is WHERE to store it"
                )

                print("\nCommands:")
                print("  /exit or /quit  - Exit")
                print("  /clear          - Clear conversation")
                print("=" * 60 + "\n")

                await self.chat_loop()

        except Exception as e:
            print(f"Error: {e}")

    


async def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_server_path = os.path.join(script_dir, "mcp_server.py")

    available_serves = [
        {
            "command": "python",
            "server_args": [mcp_server_path]
        },
        # {
        #     "command": "npx",
        #     "server_args": ["@playwright/mcp"]
        # }
    ]
    app = MCPChatApp(servers=available_serves)
    await app.start()


if __name__ == "__main__":
    asyncio.run(main())