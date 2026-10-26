import sys
import json
import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [SandboxRunner] %(message)s"
)
logger = logging.getLogger("SandboxRunner")

# Optimize Playwright Chromium launch arguments for minimum memory footprint
try:
    from playwright.async_api import BrowserType
    _orig_launch = BrowserType.launch

    async def _patched_launch(self, **kwargs):
        default_args = [
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-extensions",
            "--js-flags=--max-old-space-size=128"
        ]
        user_args = list(kwargs.get("args", []))
        for a in default_args:
            if a not in user_args:
                user_args.append(a)
        kwargs["args"] = user_args
        return await _orig_launch(self, **kwargs)

    BrowserType.launch = _patched_launch
except ImportError:
    pass

async def run(portal_id: str, output_path: str):
    logger.info(f"Starting standalone scrape for portal: {portal_id}")
    from adapter_registry import get_adapter_instance

    adapter = get_adapter_instance(portal_id)
    if not adapter:
        raise ValueError(f"Portal '{portal_id}' not found in adapter registry.")

    listings = await adapter.scrape()
    listings_data = [job.model_dump() for job in listings]
    logger.info(f"Successfully scraped {len(listings_data)} listings for '{portal_id}'")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"status": "success", "listings": listings_data}, f, ensure_ascii=False)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python sandbox_runner.py <portal_id> <output_json_path>", file=sys.stderr)
        sys.exit(2)

    portal_id = sys.argv[1]
    output_path = sys.argv[2]

    try:
        asyncio.run(run(portal_id, output_path))
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error executing adapter '{portal_id}': {e}", exc_info=True)
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump({"status": "error", "error": str(e)}, f, ensure_ascii=False)
        except Exception:
            pass
        sys.exit(1)
