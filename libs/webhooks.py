import httpx


class Webhook:
    client: httpx.AsyncClient
    url: str

    def __init__(self, url: str):
        self.url = url
        self.client = httpx.AsyncClient()

    async def __aenter__(self) -> 'Webhook':
        await self.client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.__aexit__(exc_type, exc_val, exc_tb)

    async def send_message(self, content: str | None = None, *, file_path: str | None = None):
        if content is None and file_path is None:
            raise ValueError("Must provide content or a file to upload")
        data, files = None, None
        if content is not None:
            data = {
                'content': content
            }
        if file_path is not None:
            files = {
                'file[0]': open(file_path, "rb")
            }
        await self.client.post(self.url, data=data, files=files)
        if files is not None:
            files['file[0]'].close()
