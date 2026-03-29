from agent.agent import run_agent
from mcp.server.init_tools import init_tools

def main():
    init_tools()
    
    print("MCP Energy AI Agent (Production CLI)")
    
    while True:
        query = input("\nUser: ")
        if query.lower() in ["exit", "quit", "bye"]:
            break
        
        response = run_agent(query)
        print(f"\nAgent: {response}")


if __name__ == "__main__":
    main()