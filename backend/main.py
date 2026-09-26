import argparse
import asyncio
import re
import sys

from services.context import gather_context
from services.recommender import recommend

DEFAULT_WORD = "spark"


def parse_word(raw: str) -> str:
    """Frontend will send one word; for now keep the first alphabetic token."""
    match = re.search(r"[A-Za-z]+", raw or "")
    return (match.group(0) if match else DEFAULT_WORD).lower()


def _print_list(title: str, items: list, label_keys: tuple[str, ...]) -> None:
    print(f"\n{title}")
    if not items:
        print("  (none)")
        return
    for item in items:
        if not isinstance(item, dict):
            print(f"  - {item}")
            continue
        label = " — ".join(str(item[k]) for k in label_keys if item.get(k))
        if not label:
            label = str(item.get("name") or item.get("dish") or item.get("title") or item)
        why = item.get("why")
        indoor = item.get("indoor")
        suffix = ""
        if indoor is True:
            suffix = " [indoor]"
        elif indoor is False:
            suffix = " [outdoor]"
        print(f"  - {label}{suffix}")
        if why:
            print(f"      {why}")


async def run(word: str) -> dict:
    print(f"Gathering context for: {word}")
    context = await gather_context()
    weather = context.get("weather") or {}
    time_ctx = context.get("time") or {}
    print(
        f"  {time_ctx.get('day')} {time_ctx.get('time_of_day')}"
        f" | {weather.get('condition')}, {weather.get('temperature')}°C"
        f" | indoor={ (context.get('hints') or {}).get('indoor_preferred') }"
    )
    print("Asking recommender...")
    return await recommend(word, context)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="One-word activity recommender")
    parser.add_argument(
        "word",
        nargs="?",
        default=DEFAULT_WORD,
        help=f"seed word (default: {DEFAULT_WORD})",
    )
    args = parser.parse_args()
    word = parse_word(args.word)

    try:
        suggestions = asyncio.run(run(word))
    except Exception as e:
        print(f"Failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n=== SUGGESTIONS ({suggestions.get('word')}) ===")
    print(f"Vibe : {suggestions.get('vibe')}")
    print(f"Model: {suggestions.get('model')}")
    _print_list("Music", suggestions.get("music") or [], ("title", "artist"))
    _print_list("Food", suggestions.get("food") or [], ("dish",))
    _print_list("Hobbies", suggestions.get("hobbies") or [], ("name",))
    _print_list("Activities", suggestions.get("activities") or [], ("name",))


if __name__ == "__main__":
    main()
