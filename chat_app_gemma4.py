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
from langgraph.graph import StateGraph, MessagesState, START
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

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
            temperature=0.6,
            num_ctx=6144,  # ← increase context window
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
                content = result.content
                # we strip the TextContent wrapper of every tool call from
                # [TextContent(type='text', text='Focused: WhatsApp', annotations=None, meta=None)]
                # to Focused: WhatsApp
                if isinstance(content, list) and len(content) > 0:
                    return str(content[0].text) if hasattr(content[0], "text") else str(content)
                return str(content)
            return "Tool executed successfully"

        return StructuredTool.from_function(
            coroutine=run_mcp_tool,
            name=tool_name,
            description=description,
            args_schema=DynamicSchema,
        )
    
    def _build_agent(self):
        """
        Replaces create_agent with a custom Langgrpah graph
        Enforces one tool call at a time - no batch processing (running all tool calls at the same time)
        """
        system_prompt = """You are a desktop automation assistant.

                        RULES — follow in strict order:
                        1. One tool call per turn. Always wait for the result.
                        2. To search or find something: click the Edit field labelled [USE THIS TO SEARCH/FIND] — never click a Button to search.
                        3. To send a message: click the Edit field labelled [USE THIS TO TYPE AND SEND], type the text, then press_key('enter').
                        4. After every mouse_click: call get_screen_elements again before any next action. Coordinates change.
                        5. Never reuse coordinates from a previous get_screen_elements call.
                        6. To open an app: open_application → focus_application → get_screen_elements.
                        7. When you see an Edit field labelled [USE THIS TO TYPE AND SEND MESSAGES], the navigation is complete. Do not click anything else. Use that field immediately.
                        8. If the user says 'on this page', 'on screen', 'this tab', 'current window', or gives NO app name: call get_screen_elements with NO arguments. Do NOT call open_application or focus_application first.

                        TASK FLOW for 'search and message' tasks:
                        focus_application → get_screen_elements → click [SEARCH field] → type name → get_screen_elements → click contact → get_screen_elements → click [MESSAGE field] → type message → press_key('enter')

                        TASK FLOW for 'current page' tasks:
                        get_screen_elements (no arguments) → read active window title → act on what is visible
                        """

        llm_with_tools = self.llm.bind_tools(self.langchain_tools)

        async def call_model(state: MessagesState):
            # add user message and system message together for every model call
            messages = [SystemMessage(content=system_prompt)] + state["messages"]
            response = await llm_with_tools.ainvoke(messages)

            # ── ENFORCE ONE TOOL AT A TIME ──────────────────────────
            # if the model combined multiple tool calls in its response, keep only the first
            if hasattr(response, "tool_calls") and len(response.tool_calls) > 1:
                print(f"Model tried to call {len(response.tool_calls)} tools at once now trimming to one")

                # replace all other tool calls with the first tool call choice made by the model
                response.tool_calls = [response.tool_calls[0]]
            # ────────────────────────────────────────────────────────

            if response.tool_calls:
                for tc in response.tool_calls:
                    print(f"  🔧 {tc['name']}({tc['args']})")
            else:
                print(f"  💬 Model finished — writing final response")

            usage = response.usage_metadata
            if usage:
                input_tokens = usage["input_tokens"]
                output_tokens = usage["output_tokens"]
                total_tokens = usage['total_tokens']
                print(f"📊 tokens: {input_tokens} in / {output_tokens}  out / {total_tokens} total (limit: {self.llm.num_ctx})")
            # this response gets added to the MessagesState with each call of call_model
            # state["messages"] = [response1]
            # state["messages"] = [response1, response2]
            # response would be an object either AIMessage or HumanMessage or ToolMessage
            return {"messages": [response]}
        
        def should_continue(state: MessagesState):
            """
            call_model handles getting the model response and filtering out to the first response 
            This then 
            """
            # state["messages"] contains multiple responses which are various object AIMessage or HumanMessage or ToolMessage
            # here we check the response the Ai returned (via AIMessage object) does it have a value within the tool_calls parameter
            last_message = state["messages"][-1]
            if last_message.tool_calls:
                return "tools"
            return "__end__"
        
        original_tool_node  = ToolNode(self.langchain_tools)

        async def tool_node_with_logging(state: MessagesState, config: RunnableConfig):
            result = await original_tool_node.ainvoke(state, config)
            for msg in result["messages"]:
                preview = str(msg.content)[:120].replace('\n', ' ')
                print(f"  ✅ {msg.name}: {preview}")
            return result
        
        # build the graph
        graph = StateGraph(MessagesState)

        # when graph arrives at "agent" node → automatically calls call_model(state)
        graph.add_node("agent", call_model)

        # when graph arrives at "tools" node → automatically calls tool_node_with_logging
        graph.add_node("tools", tool_node_with_logging)

        # When START is invoked ALWAYS go back to agent node
        # no decision needed, unconditional
        graph.add_edge(START, "agent")

        # FROM the agent node, run should_continue to decide where to go next
        # if should_continue returns "tools" → go to tools node
        # if should_continue returns "__end__" → stop
        graph.add_conditional_edges("agent", should_continue)

        # FROM the tools node, ALWAYS go back to agent node
        # no decision needed, unconditional
        graph.add_edge("tools", "agent")

        return graph.compile(checkpointer=self.checkpointer)
    
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
                print(f"\nAssistant> {assistant_message}\n")

            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {e}\n")

    # you pass this in chat_loop:
    # {"messages": [{"role": "user", "content": "search for Skylah"}]}

    # in _build_model
    # graph merges with checkpointer history and delivers as:
    # state = {
    #    "messages": [
    #        HumanMessage("open WhatsApp"),   # from checkpointer
    #        AIMessage("Opened WhatsApp"),    # from checkpointer
    #        HumanMessage("search for Skylah") # your new message
    #    ]
    #}

    # which call_model receives as:
    # async def call_model(state: MessagesState):
    #    state["messages"]  # ← that exact list above

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
                            


                self.agent = self._build_agent()

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