import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


def fetch_url(url: str, timeout: int):
    try:
        response = requests.get(url, timeout=timeout)
        return url, response.status_code, response.text[:200]
    except requests.exceptions.RequestException as e:
        return url, None, str(e)


def main():
    target_url = input("Enter the API URL to test: ").strip() or "https://ashishkr45.me/"

    try:
        request_count = int(input("Enter the number of requests: ").strip())
    except ValueError:
        request_count = 20

    try:
        thread_count = int(input("Enter the thread count: ").strip())
    except ValueError:
        thread_count = 4

    try:
        timeout = int(input("Enter timeout in seconds: ").strip())
    except ValueError:
        timeout = 5

    request_count = max(1, min(request_count, 5000))
    thread_count = max(1, min(thread_count, 100))

    print(f"Sending {request_count} requests to {target_url} using {thread_count} thread(s)...")

    success = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=thread_count) as executor:
        futures = [executor.submit(fetch_url, target_url, timeout) for _ in range(request_count)]

        for future in as_completed(futures):
            _, status_code, content = future.result()
            if status_code == 200:
                success += 1
                print(f"OK -> {status_code}")
            else:
                failed += 1
                print(f"FAIL -> {status_code}: {content[:120]}")

    print(f"Completed. Success={success}, Failed={failed}")


if __name__ == "__main__":
    main()
