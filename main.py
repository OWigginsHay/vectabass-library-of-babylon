import pickle
import random
import shutil
from uuid import uuid4

import chromadb
from package import APIWrapper, CloudDelivery
from dataclasses import dataclass, field, asdict
from typing import List
import logging
from pydantic import BaseModel, Field
import requests
from bs4 import BeautifulSoup
import os


def fetch_isbn(author, title):
    base_url = "https://isbnsearch.org/search"
    query_params = {"s": f"{title} {author}"}
    response = requests.get(base_url, params=query_params)

    if response.status_code == 200:
        soup = BeautifulSoup(response.content, "html.parser")
        try:
            isbn_link = soup.find("div", class_="image").find("a")["href"]
            isbn = isbn_link.split("/")[-1]  # Extract ISBN from the URL
            return isbn
        except Exception as e:
            print(f"Failed to extract ISBN due to an error: {e}")
            return None
    else:
        print("Failed to fetch ISBN")
        return None


def fetch_book_cover_url(isbn):
    if isbn:
        response = requests.get(
            f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
        )
        if response.status_code == 200:
            data = response.json()
            if data["totalItems"] > 0:
                try:
                    thumbnail_url = data["items"][0]["volumeInfo"]["imageLinks"][
                        "thumbnail"
                    ]
                    return thumbnail_url
                except KeyError:
                    print("Thumbnail URL not available.")
                    return ""
            else:
                print("No books found with the given ISBN.")
                return ""
        else:
            print("Failed to fetch data from Google Books API.")
            return ""
    else:
        print("Invalid ISBN provided.")
        return ""


def search_book_and_get_details(author, title):
    search_query = f"{title}+inauthor:{author}"
    url = f"https://www.googleapis.com/books/v1/volumes?q={search_query}"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        if data["totalItems"] == 0:
            print("No results found.")
            return None, None
        else:
            book_info = data["items"][0]["volumeInfo"]

            # Extract ISBN
            isbn = None
            for identifier in book_info.get("industryIdentifiers", []):
                if identifier["type"] == "ISBN_13":
                    isbn = identifier["identifier"]
                    break

            # Extract thumbnail URL
            thumbnail_url = book_info.get("imageLinks", {}).get("thumbnail", "")

            return isbn, thumbnail_url
    else:
        print("Failed to fetch data from Google Books API.")
        return None, None


def initialize_persistent_chroma_client(db_path="chroma_db"):
    # Ensure the directory exists (create if it doesn't)
    os.makedirs(db_path, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=db_path)
    return chroma_client


def zip_chroma_db(db_path="chroma_db", zip_path="chroma_db.zip"):
    shutil.make_archive(base_name=db_path, format="zip", root_dir=db_path)


def unzip_chroma_db(zip_path="chroma_db.zip", extract_path="."):
    shutil.unpack_archive(zip_path, extract_path)


def get_chroma_client_state_path():
    return "chroma_state.pkl"


def get_or_initialize_chroma_client():
    zip_path = "chroma_db.zip"
    db_path = "chroma_db"

    # Attempt to download the Chroma DB zip from cloud storage
    try:
        download_chroma_state_from_cloud(zip_path)
        unzip_chroma_db(zip_path, db_path)
    except Exception as e:
        logging.info(f"No existing Chroma DB state found or failed to download: {e}")

    # Initialize the Chroma client with the potentially unzipped DB path
    chroma_client = initialize_persistent_chroma_client(db_path)
    collection = chroma_client.get_or_create_collection(name="books")

    return chroma_client, collection


# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Adjust as needed
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log"),  # Log messages to a file
        logging.StreamHandler(),  # And also to standard output
    ],
)

logging.info("Logging setup complete.")

api_wrapper = APIWrapper(
    api_key="6bbdc8e3-289f-425f-a474-8a004bef5210",
    upload_url="https://intermediary-server-service-4dvqi5ecwa-nw.a.run.app",
)


class BookEntry(BaseModel):
    author: str
    book_name: str
    comments: List[str] = Field(default_factory=list)
    genre: str
    topics: List[str] = Field(default_factory=list)
    mood: str
    similar_books: List[str] = Field(default_factory=list)
    rating: float


class QueryEntries(BaseModel):
    query_text: str
    sample_size: int


class RandomSample(BaseModel):
    sample_size: int


import json


def add_book_entry_to_chroma(collection, book_entry: BookEntry):
    # Attempt to fetch the ISBN and cover URL
    isbn, cover_url = search_book_and_get_details(
        book_entry.author, book_entry.book_name
    )

    # Serialize list fields into JSON strings and include the cover URL
    metadata = {
        "comments": json.dumps(book_entry.comments),
        "similar_books": json.dumps(book_entry.similar_books),
        "topics": json.dumps(book_entry.topics),
        "mood": book_entry.mood,
        "rating": book_entry.rating,
        "cover_url": cover_url,  # Append cover URL here
    }

    # Generate a unique ID for the book entry
    id = f"{book_entry.book_name}:{book_entry.author}"

    # Combine textual information for embedding
    document_text = f"{book_entry.book_name} by {book_entry.author}. Genre: {book_entry.genre}. Mood: {book_entry.mood}. Rating: {book_entry.rating}."

    # Add the document to the collection with metadata
    collection.add(documents=[document_text], metadatas=[metadata], ids=[id])


csv_file_path = "books_registry.csv"


def upload_chroma_state_to_cloud(file_path="chroma_db.zip"):
    # Use CloudDelivery to upload the zip file
    CloudDelivery.upload_file_to_gcp(file_path)
    logging.info(f"Chroma DB zip uploaded successfully: {file_path}")


def download_chroma_state_from_cloud(file_path="chroma_db.zip"):
    # Use CloudDelivery to download the zip file
    CloudDelivery.download_file_from_gcp(file_path)
    logging.info(f"Chroma DB zip downloaded successfully: {file_path}")


def download_chroma_state_from_cloud(file_path: str):
    """
    Downloads the Chroma state file from cloud storage to a local path.
    """
    try:
        # Using CloudDelivery to download the Chroma state file
        CloudDelivery.download_file_from_gcp(file_path)
        logging.info(f"Chroma state file downloaded successfully: {file_path}")
    except Exception as e:
        logging.error(f"Failed to download Chroma state file: {e}")
        # Handle exception or decide to initialize a new state if necessary


def upload_chroma_state_to_cloud(file_path: str):
    """
    Uploads the Chroma state file from a local path to cloud storage.
    """
    try:
        # Using CloudDelivery to upload the Chroma state file
        CloudDelivery.upload_file_to_gcp(file_path)
        logging.info(f"Chroma state file uploaded successfully: {file_path}")
    except Exception as e:
        logging.error(f"Failed to upload Chroma state file: {e}")
        # Handle exception or retry as needed


@api_wrapper.endpoint()
async def register_entry(book_entry: BookEntry):
    try:
        chroma_client, collection = get_or_initialize_chroma_client()
        logging.info(f"Processing book entry: {book_entry}")
        add_book_entry_to_chroma(collection, book_entry)

        # Zip the Chroma DB and upload the zip to cloud storage
        zip_chroma_db("chroma_db", "chroma_db.zip")
        upload_chroma_state_to_cloud("chroma_db.zip")

        return {"message": "Book registered successfully."}
    except Exception as e:
        logging.error(f"Error registering book: {e}")
        return {"error": str(e)}


@api_wrapper.endpoint()
async def sample_random_entries(query: RandomSample):
    try:
        chroma_client, collection = get_or_initialize_chroma_client()
        total_entries = collection.count()

        # Adjust the limit based on the sample size and total entries
        limit = min(query.sample_size, total_entries)

        # Fetch a sample of entries
        sampled_entries_result = collection.peek(limit=limit)

        # Assuming sampled_entries_result is a GetResult object containing a list of entries
        sampled_entries_result.pop("embeddings", None)

        return {"sampled_entries": sampled_entries_result}
    except Exception as e:
        logging.error(f"Error sampling entries: {e}")
        return {"error": str(e)}


@api_wrapper.endpoint()
async def query_entries(query: QueryEntries):
    try:
        chroma_client, collection = get_or_initialize_chroma_client()

        # Define your query. This example uses query_texts for simplicity.
        results = collection.query(
            query_texts=[query.query_text],
            n_results=query.sample_size,
            include=[
                "metadatas",
                "documents",
                "distances",
            ],  # Adjust based on what you want returned
        )

        return {"query_results": results}
    except Exception as e:
        logging.error(f"Error querying entries: {e}")
        return {"error": str(e)}


app = api_wrapper.app

if __name__ == "__main__":
    print(api_wrapper.deploy_project(app_name="vectabass-library-of-babylon"))
    print(
        api_wrapper.get_and_update_openapi(
            api_wrapper.get_url_for_app("vectabass-library-of-babylon")
        )
    )
