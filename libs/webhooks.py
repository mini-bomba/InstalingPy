import httpx


class Webhook:
    client: httpx.AsyncClient
    url: str
    retries: int

    def __init__(self, url: str, *, timeout: float = 30, retries: int = 3):
        self.url = url
        self.client = httpx.AsyncClient(timeout=timeout)
        self.retries = retries

    async def __aenter__(self) -> 'Webhook':
        await self.client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.__aexit__(exc_type, exc_val, exc_tb)

    async def send_message(self, content: str | None = None, *, file_path: str | list[str] | None = None):
        if content is None and (isinstance(file_path, str) or (isinstance(file_path, list) and len(file_path) >= 1)):
            raise ValueError("Must provide content or a file to upload")
        data, files = None, None
        if content is not None:
            data = {
                'content': content
            }
        if isinstance(file_path, str):
            files = {
                'file[0]': open(file_path, "rb")
            }
        elif isinstance(file_path, list):
            files = {
                f'file[{i}]': open(path, "rb")
                for i, path in enumerate(file_path)
            }
        try:
            for i in range(self.retries):
                try:
                    await self.client.post(self.url, data=data, files=files)
                    break
                except Exception:
                    if i == self.retries - 1:
                        raise
        finally:
            if files is not None:
                for file in files.values():
                    file.close()
