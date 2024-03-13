import requests


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


# Example usage
author = "William Golding"
title = "Lord of the Flies"
isbn, thumbnail_url = search_book_and_get_details(author, title)

if isbn and thumbnail_url:
    print(f"Fetched ISBN: {isbn}")
    print(f"Thumbnail URL: {thumbnail_url}")
else:
    print("Failed to fetch book details.")
