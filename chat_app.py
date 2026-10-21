import asyncio
import json
import os
from typing import Optional, Any, Dict, List
from mcp_client import SimpleMCPClient
from mcp import types
from groq import Groq
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class MCPChatApp:
    """
    A chat application that combines Groq LLM with MCP tools.
    Users can chat with Groq model and it can call MCP tools as needed.
    """
    
    def __init__(self, server_command: str, server_args: list[str]):
        # Initialize the MCP client that will communicate with the MCP server
        self.client = SimpleMCPClient(command=server_command, args=server_args)
        
        # Store available tools from MCP server
        self.mcp_tools = []
        
        # Initialize Groq client for LLM interaction
        self.groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        # Keep track of conversation history for multi-turn conversations
        self.messages = []
        
        # Store the Groq-formatted tools definitions
        self.groq_tools = []

    def _convert_mcp_to_groq_tool(self, mcp_tool: types.Tool) -> Dict[str, Any]:
        """
        Create Groq tool definition from an MCP tool definition.

        :param: mcp_tool: An MCP tool definition object
        :return: A dictionary representing the tool in Groq's expected format
        """
        # Create the base tool structure
        groq_tool = {
            "type": "function",
            "function": {
                "name": mcp_tool.name,
                "description": mcp_tool.description or f"Execute {mcp_tool.name}",
            }
        }

        # Convert the input schema - this defines what parameters the tool accepts
        if mcp_tool.inputSchema:
            groq_tool["function"]["parameters"] = {
                "type": "object",
                "properties": mcp_tool.inputSchema.get("properties", {}),
                "required": mcp_tool.inputSchema.get("required", [])
            }
        else:
            # If no schema provided, create an empty one
            groq_tool["function"]["parameters"] = {
                "type": "object",
                "properties": {}
            }

        return groq_tool

    async def start(self):
        """
        Initialize the MCP connection and start the chat loop.
        This is the main entry point for the application.
        """
        print("=" * 60)
        print("MCP Chat Application with Groq LLM")
        print("=" * 60)

        # Check if Groq API key is set
        if not os.getenv("GROQ_API_KEY"):
            print("Error: GROQ_API_KEY not found in environment variables")
            print("Please add GROQ_API_KEY to your .env file")
            return

        print("Creating connection to MCP server...")

        try:
            # Create client context manager and connect to MCP server
            async with self.client as client:
                # Retrieve all available tools from the MCP server
                self.mcp_tools = await client.list_tools()

                # Convert all MCP tools to Groq-compatible format
                self.groq_tools = [self._convert_mcp_to_groq_tool(tool) for tool in self.mcp_tools]

                # Display connected tools to user
                print(f"\nConnected! Available tools:")
                for tool in self.mcp_tools:
                    print(f"  • {tool.name}: {tool.description}")
                    # Show tool parameters if they exist
                    if tool.inputSchema:
                        params = tool.inputSchema.get("properties", {})
                        if params:
                            print(f"    Parameters: {', '.join(params.keys())}")

                print("\n" + "=" * 60)
                print("Commands:")
                print("  /clear          - Clear conversation history")
                print("  /tools          - List available tools")
                print("  /help           - Show this help message")
                print("  /exit or /quit  - Exit the application")
                print("=" * 60 + "\n")

                # Start the main chat loop
                await self.chat_loop()

        except Exception as e:
            print(f"Error connecting to MCP server: {e}")

    async def chat_loop(self):
        """
        Main chat interaction loop.
        Handles user input, sends to Groq, processes tool calls, and displays responses.
        """
        print("Chat with Groq (type /help for commands)\n")

        while True:
            try:
                # Get user input from terminal
                user_input = await asyncio.to_thread(input, "You> ") # Get input in a non-blocking way, using asyncio.to_thread to avoid blocking the event loop
                user_input = user_input.strip() # strip whitespace

                # Skip empty input
                if not user_input:
                    continue

                # Handle special commands
                if user_input.startswith("/"):
                    if await self.handle_command(user_input):
                        continue
                    else:
                        # /exit or /quit command returns False
                        break

                # Add user message to conversation history
                self.messages.append({"role": "user", "content": user_input})

                # Get response from Groq (with tool calling capability)
                response = await self.get_groq_response()

                # Display the response to user
                if response:
                    print(f"\nAssistant> {response}\n")

            except (KeyboardInterrupt, EOFError):
                # Handle Ctrl+C gracefully
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {e}\n")

    async def get_groq_response(self) -> Optional[str]:
        """
        Get response from Groq model, handling tool calls if needed.
        This is the core logic that:
        1. Sends message to Groq
        2. Checks if Groq wants to use tools
        3. Executes tools and sends results back
        4. Gets final response
        """
        try:
            # Call Groq API with the conversation history and available tools
            response = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",  # Using Groq's model
                max_tokens=1024,
                messages=self.messages,
                tools=self.groq_tools if self.groq_tools else None,  # Pass tools if available
            )

            # Extract the response content
            assistant_message = response.choices[0].message

            # Check if Groq wants to call any tools
            if assistant_message.tool_calls:
                # Store assistant's response in history
                self.messages.append({
                    "role": "assistant",
                    "content": assistant_message.content or "",
                    "tool_calls": assistant_message.tool_calls
                })

                # Execute all requested tool calls
                tool_results = await self.execute_tool_calls(assistant_message.tool_calls)

                # Add tool results to conversation history
                self.messages.append({
                    "role": "user",
                    "content": tool_results
                })

                # Get final response from Groq after tool execution
                final_response = self.groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    max_tokens=1024,
                    messages=self.messages,
                )

                # Extract and store final response
                final_content = final_response.choices[0].message.content
                self.messages.append({
                    "role": "assistant",
                    "content": final_content
                })

                return final_content
            else:
                # No tool calls, just return the response
                content = assistant_message.content or ""
                
                # Store response in message history
                self.messages.append({
                    "role": "assistant",
                    "content": content
                })

                return content

        except Exception as e:
            return f"Error getting response from Groq: {e}"

    async def execute_tool_calls(self, tool_calls) -> str:
        """
        Execute tool calls requested by Groq.
        Each tool call is passed to the MCP server for execution.
        Returns the results formatted for Groq to understand.
        """
        # Will store results from all tool calls
        all_results = []

        # Process each tool call from Groq
        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            
            # Parse the arguments JSON string
            try:
                # example of tool_call.function.arguments: '{"filepath": "./docs/sample_doc.txt"}'
                tool_arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_arguments = {}

            print(f"[Calling MCP tool: {tool_name} with args: {tool_arguments}]")

            try:
                # Execute the tool through MCP client
                result = await self.client.call_tool(tool_name, tool_arguments)

                # Extract text content from result
                result_text = str(result.content) if result.content else "Tool executed successfully"

                # Store the result
                all_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": result_text
                })

            except Exception as e:
                # Store error if tool execution fails
                all_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": f"Error executing tool: {str(e)}"
                })

        # Format results as JSON for Groq to understand
        return json.dumps(all_results)

    async def handle_command(self, command: str) -> bool:
        """
        Handle chat commands like /help, /clear, etc.
        Returns True to continue chatting, False to exit.
        """
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()

        if cmd in ["/exit", "/quit"]:
            print("Goodbye!")
            return False

        elif cmd == "/help":
            print("\nCommands:")
            print("  /clear          - Clear conversation history")
            print("  /tools          - List available tools")
            print("  /help           - Show this help message")
            print("  /exit or /quit  - Exit the application\n")

        elif cmd == "/clear":
            # Clear conversation history to start fresh
            self.messages = []
            print("Conversation history cleared.\n")

        elif cmd == "/tools":
            # Display all available tools
            print("\nAvailable tools:")
            for tool in self.mcp_tools:
                print(f"  • {tool.name}: {tool.description}")
                if tool.inputSchema:
                    params = tool.inputSchema.get("properties", {})
                    if params:
                        print(f"    Parameters: {', '.join(params.keys())}")
            print()

        else:
            print(f"Unknown command: {cmd}")
            print("Type /help for available commands\n")

        return True


async def main():
    """
    Main entry point for the application.
    Sets up the MCP server configuration and starts the chat app.
    """
    # Get absolute path to mcp_server.py
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_server_path = os.path.join(script_dir, "mcp_server.py")
    
    # Configure how to run the MCP server
    use_uv = os.getenv("USE_UV", "0") == "1"

    if use_uv:
        server_command = "uv"
        server_args = ["run", mcp_server_path]
    else:
        server_command = "python"
        server_args = [mcp_server_path]

    # Create and start the chat application
    app = MCPChatApp(server_command, server_args)

    try:
        await app.start()
    except Exception as e:
        print(f"Fatal error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    # Run the async main function
    exit_code = asyncio.run(main())
    exit(exit_code)