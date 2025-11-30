from ddgs import DDGS  # The new, updated import
from rich import print
import time

def ddgs_test_query(query: str, max_results: int = 5):
    """
    Performs a DuckDuckGo search using the updated DDGS syntax.
    """
    print(f"\n[bold green]Attempting DuckDuckGo Search for: '{query}'...[/bold green]")
    start_time = time.time()

    try:
        # The DDGS() class is now used directly
        with DDGS() as ddgs:
            # *** THE FIX IS HERE: The parameter is now 'query' and is passed positionally ***
            results = list(ddgs.text(
                query=query,          # Changed from keywords= to query=
                region='us-en',
                max_results=max_results,
            ))

        end_time = time.time()
        
        if not results:
            print("[bold yellow]Warning:[/bold yellow] Request successful, but no results were returned.")
            return

        # Success case
        print(f"[bold blue]Success![/bold blue] Found {len(results)} results in {end_time - start_time:.2f} seconds.")
        print("-" * 40)
        
        for i, result in enumerate(results, 1):
            print(f"[bold white]{i}. {result.get('title', 'No Title')}[/bold white]")
            print(f"   [link={result.get('href', 'No URL')}]URL:[/link] {result.get('href', 'No URL')}")
            # Snippet key remains 'body' in the output
            print(f"   Snippet: {result.get('body', 'No snippet')[:100]}...") 
            print("")

    except Exception as e:
        # Failure case for network/rate limiting
        print(f"[bold red]CRITICAL FAILURE:[/bold red] An error occurred during the search.")
        print(f"[bold red]Error Type:[/bold red] {type(e).__name__}")
        print(f"[bold red]Error Message:[/bold red] {e}")
        print("\n[italic yellow]Common causes for this error:[/italic yellow]")
        print("* IP has been temporarily blocked/rate-limited by DuckDuckGo.")
        print("* Network or DNS resolution failure.")


if __name__ == "__main__":
    test_query = "latest AI model releases 2025"
    ddgs_test_query(test_query)