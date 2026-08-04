import requests
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


def fetch_url(session: requests.Session, url: str, timeout: float):
    try:
        response = session.get(url, timeout=timeout)
        return True, response.status_code, response.text[:120]
    except requests.exceptions.RequestException as e:
        return False, None, str(e)[:120]


def main():
    target_url = input("Enter the API URL to test: ").strip() or "https://ashishkr45.me/"

    try:
        request_count = int(input("Enter the number of requests: ").strip())
    except ValueError:
        request_count = 2000

    try:
        thread_count = int(input("Enter the thread count: ").strip())
    except ValueError:
        thread_count = 200

    try:
        timeout = float(input("Enter timeout in seconds: ").strip())
    except ValueError:
        timeout = 3.0
    success = 0
    failed = 0
    completed = 0
    in_flight = 0
    last_status = 0
    lock = threading.Lock()

    start_time = time.time()

    with requests.Session() as session:
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=thread_count,
            pool_maxsize=thread_count
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        def task():
            nonlocal in_flight
            with lock:
                in_flight += 1
            ok, status_code, content = fetch_url(session, target_url, timeout)
            with lock:
                in_flight -= 1
            return ok, status_code, content

        with ThreadPoolExecutor(max_workers=thread_count) as executor:
            futures = [executor.submit(task) for _ in range(request_count)]

            for future in as_completed(futures):
                ok, status_code, _ = future.result()

                with lock:
                    completed += 1
                    if ok and status_code and 200 <= status_code < 400:
                        success += 1
                        last_status = status_code
                    else:
                        failed += 1
                        last_status = status_code if status_code is not None else 0

                    progress = (completed / request_count) * 100
                    elapsed = time.time() - start_time
                    rps = completed / elapsed if elapsed > 0 else 0.0

                    line = (
                        f"ok {last_status} || "
                        f"request_count {completed}/{request_count} || "
                        f"progress {progress:.5f}% || "
                        f"success {success} || failed {failed} || "
                        f"in_flight {in_flight} || rps {rps:.2f}"
                    )

                    # single-line auto-updating output
                    print("\r" + line.ljust(140), end="", flush=True)

    total_time = time.time() - start_time
    print()  # final newline once at end
    print(f"Completed in {total_time:.2f}s | Avg RPS {(request_count / total_time) if total_time > 0 else 0:.2f}")


if __name__ == "__main__":
    main()
