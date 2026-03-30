from agent.agent import run_agent
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

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