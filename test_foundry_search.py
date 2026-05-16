"""Test Foundry upload and debug 400 boundary errors."""
import sys
sys.path.insert(0, "/app")
import asyncio, httpx

async def main():
    from app.services.azure_foundry_service import (
        upload_file_to_foundry,
        _get_agents_bearer_token,
        _threads_base,
        _THREADS_API_VERSION,
    )
    from app.config import settings

    print(f"AZURE_AI_FOUNDRY_KEY set: {bool(settings.AZURE_AI_FOUNDRY_KEY)}")
    print(f"CLIENT_ID set: {bool(settings.AZURE_CLIENT_ID)}")
    print(f"CLIENT_SECRET set: {bool(settings.AZURE_CLIENT_SECRET)}")

    # Test upload via actual function
    print("\n--- Test upload_file_to_foundry ---")
    try:
        fid = await upload_file_to_foundry("test.txt", b"hello world")
        print(f"SUCCESS: {fid}")
    except Exception as e:
        print(f"FAILED: {e}")

    # Test raw upload with explicit headers (no Content-Type)
    print("\n--- Raw upload test ---")
    try:
        token = _get_agents_bearer_token()
        print(f"Token obtained (len={len(token)})")
        base = _threads_base()
        ver = _THREADS_API_VERSION
        hdrs = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(
                f"{base}/files?api-version={ver}",
                headers=hdrs,
                files={"file": ("test2.txt", b"world", "text/plain")},
                data={"purpose": "assistants"},
            )
            print(f"Status: {r.status_code}")
            if r.status_code == 200:
                print(f"  file_id: {r.json()['id']}")
            else:
                print(f"  body: {r.text[:300]}")
    except Exception as e:
        print(f"RAW FAILED: {e}")

asyncio.run(main())
