import requests
import json

# Endpoint URL
url = "https://vectabass-library-of-babylon-4dvqi5ecwa-nw.a.run.app/register_entry"

# Data to be sent to API
data = {
    "author": "John Doe",
    "book_name": "The Adventures of Sherlock Holmes",
    "genre": "Mystery",
    "mood": "Suspenseful",
    "rating": 4.5,
    "metadata": json.dumps(
        {
            "comments": ["Intriguing", "Captivating narrative"],
            "topics": ["Detective", "London", "Investigation"],
            "similar_books": ["The Hound of the Baskervilles", "A Study in Scarlet"],
        }
    ),
}

# Headers
headers = {"Accept": "application/json", "Content-Type": "application/json"}

# Sending post request and saving response as response object
try:
    response = requests.post(url, data=json.dumps(data), headers=headers)

    # Check if the request was successful
    if response.status_code == 200:
        print("Successfully registered the book entry.")
        print("Response:", response.json())  # Print the response data
    else:
        print(f"Failed to register the book entry. Status code: {response.status_code}")
        print("Response:", response.text)  # Print the response text for debugging
except requests.exceptions.RequestException as e:
    # For handling exceptions that may be thrown during the request
    print(f"An error occurred: {e}")
