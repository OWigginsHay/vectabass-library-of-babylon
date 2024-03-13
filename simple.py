from package import APIWrapper
from pydantic import BaseModel

api_wrapper = APIWrapper(
    api_key="6bbdc8e3-289f-425f-a474-8a004bef5210",
    upload_url="https://intermediary-server-service-4dvqi5ecwa-nw.a.run.app",
)


class BookEntry(BaseModel):
    author: str


@api_wrapper.endpoint()
async def register_entry(book_entry: BookEntry):
    ...
    return ""


app = api_wrapper.app

if __name__ == "__main__":
    print(api_wrapper.deploy_project(app_name="vectabass-library-of-babylon"))
    print(
        api_wrapper.get_and_update_openapi(
            api_wrapper.get_url_for_app("vectabass-library-of-babylon")
        )
    )
