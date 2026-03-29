from agent.agent import run_agent

def main():
    print("⚡ Energy AI Agent (MCP Enabled)")
    print("Type 'exit' to quit\n")

    while True:
        query = input(">> ")

        if query.lower() in ["exit", "quit"]:
            print("Goodbye 👋")
            break

        try:
            response = run_agent(query)
            print("\n🤖", response, "\n")

        except Exception as e:
            print(f"\n❌ Error: {str(e)}\n")


if __name__ == "__main__":
    main()