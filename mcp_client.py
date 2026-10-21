import asyncio
from typing import Optional, Any
from pydantic import AnyUrl
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp import types

class SimpleMCPClient:
    """
    This class enables an application to connect to an MCP server using stdio transport.

    :param command: The command the client will use to start the MCP server process (e.g., "python", "uv").
    :param args: Depending on the command used, this could be the path to the MCP server script and any additional arguments (e.g., ["./mcp_server.py"] or ["run", "mcp_server.py"]).
    :param env: Optional environment variables to set for the MCP server process.
    """
    def __init__(self, command: str, args: list[str], env: Optional[dict[str, str]] = None):
        self.command = command
        self.args = args
        self.env = env
        # This will hold the ClientSessions instance after connecting to the MCP server using the stdio transport.
        # its a class variable because we want to use the same sessions across different methods in the class, such as list_tools and call_tool, which requires an active ClientSession.
        self.session: Optional[ClientSession] = None 

        # This is used to manage the lifecycle of the stdio transport and the ClientSession, ensuring that resources are properly cleaned up when they are no longer needed.
        self.exist_stack = AsyncExitStack() 

    async def connect_to_mcp_server(self):
        """Connects to the MCP server using stdio transport.
        """
        print("Connecting to MCP server...")
        server_params = StdioServerParameters(
            command = self.command,
            args = self.args,
            env = self.env,
        )

        stdio_transport = await self.exist_stack.enter_async_context(
            # with the parameters passed from the frontend (e.g., command="python", args=["./mcp_server.py"]),
            # we start/run the MCP server file as a separate program using the stdio_client (which is like a transport system)
            # this opens a way to talk to the mcp server (send messages to it and get messages back).
            stdio_client(server_params)
        )

        # After starting the MCP server and opening the connection,
        # we get two things:
        # - one for reading messages coming from the server (stdout_reader)
        # - one for sending messages to the server (stdin_writer)
        # think of it like a chat:
        # we "write" to send something, and "read" to get a response back
        #
        # these will be used by ClientSession so we don’t have to manually handle
        # sending and receiving raw messages ourselves
        self.stdio, self.write = stdio_transport

        self.session = await self.exist_stack.enter_async_context(
            # Create a ClientSession using the read and write methods from the connection.
            # we could use those methods directly, but that would mean handling everything ourselves
            # (sending messages, waiting for replies, keeping things in sync).
            # this wraps that logic for us so interacting with the MCP server is much simpler.
            ClientSession(self.stdio, self.write)
        )

        await self.session.initialize()

    def session(self) -> ClientSession:
        if self.session is None:
            raise ConnectionError("Not connected to MCP server via ClientSession.")
        return self.session

    async def list_tools(self) -> list[types.Tool]:
        """Lists the tools available on the MCP server.
            ask the server: "show me all the functions you exposed as tools"
            (i.e. everything you marked with @mcp.tool)
            it returns their names + descriptions + what inputs they expect
        """
        result = await self.session.list_tools()
        return result.tools
        
    async def call_tool(self, tool_name: str, tool_input) -> types.CallToolResult:
        """Calls a tool on the MCP server with the given arguments.
            this tells the server:
            "check the tools you have (the ones marked with @mcp.tool),
            find the one with this name (e.g. 'write_doc'),
            and run it using these tool_input"
        """
        return await self.session.call_tool(tool_name, tool_input)
        
    async def read_resource(self, uri: str) -> Any:
        result = await self.session.read_resource(AnyUrl(uri))
        if not result.contents:
            return ""
            
        resource = result.contents[0]

        if isinstance(resource, types.TextResourceContents):
            return resource.text # Get the text
        elif isinstance(resource, str):
            return resource # Get base64-encoded binary 
            
        return str(resource)
    
    async def cleaup(self):
        """Clean up resources handling with AsyncExitStack.
        """
        await self.exist_stack.aclose()
        self.session = None
    
    async def __aenter__(self):
        await self.connect_to_mcp_server()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleaup()

async def main():
    async with SimpleMCPClient(command="python", args=["./mcp_server.py"]) as client:
        tools = await client.list_tools()
        print(f"Available tools: {[tool.name for tool in tools]}")

        result = await client.call_tool("read_doc", {"filepath": "E:\AiAgentsGood\AiAgents\hello.txt"})
        if result:
            print(f"Content of sample_doc,txt was read successfully: {result.content}")


if __name__ == "__main__":
    asyncio.run(main())
        