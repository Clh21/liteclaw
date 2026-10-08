from mcp.server.fastmcp import FastMCP

server = FastMCP("liteclaw-demo")


@server.tool(description="Echo a short message")
def echo(message: str) -> str:
    return message


if __name__ == "__main__":
    server.run(transport="stdio")
