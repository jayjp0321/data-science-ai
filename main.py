from agent.agent import run_agent, _cleanup_mcp
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def main():
    print("⚡ Energy AI Agent (MCP Enabled)")
    print("Type 'exit' to quit\n")

    while True:
        try:
            query = input(">> ")

            if query.lower() in ["exit", "quit"]:
                _cleanup_mcp()
                print("Goodbye 👋")
                break

            if not query.strip():       # ← ignore empty inputs
                continue

            response = run_agent(query) # ← THIS WAS MISSING
            print("\n🤖", response, "\n")

        except KeyboardInterrupt:       # ← Ctrl+C graceful exit
            print("\n\nInterrupted — shutting down...")
            _cleanup_mcp()
            break

        except Exception as e:
            print(f"\n❌ Error: {str(e)}\n")
            # ← does NOT break the loop, continues to next query


if __name__ == "__main__":
    main()