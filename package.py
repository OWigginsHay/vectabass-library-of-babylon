import datetime
from dis import Instruction
from typing import Any, Callable, List, TypeVar, get_type_hints
from fastapi import Body, Depends, FastAPI, Response
from fastapi.encoders import jsonable_encoder
from fastapi.routing import APIRoute
import subprocess
import time
import git
from git import Repo
import os
import tempfile
import shutil
import sys
import zipfile
import requests
from pydantic import BaseModel, Field, NoneBytes, create_model
from typing import Callable, List
import inspect
import logging
from functools import wraps

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
T = TypeVar("T")  # Generic type for function return types


class GenericResponseModel(BaseModel):
    data: Any


class DeploymentResponse(BaseModel):
    message: str
    url: str = None
    build_id: str = None
    instructions: str = None


class APIWrapper:
    def __init__(self, api_key, upload_url):
        self.app = FastAPI()
        self.api_key = api_key
        self.upload_url = upload_url
        self.user = "user-oli"
        # self._validate_api_key()

    def _generate_unique_datetime_stamp(self):
        return datetime.datetime.now().strftime("%Y%m%d%H%M%S")

    def _validate_api_key(self):
        """Vaidate an API KEY"""
        validation_endpoint = f"{self.upload_url}/validate_api_key"
        response = requests.post(validation_endpoint, json={"api_key": self.api_key})
        if response.status_code == 200 and response.json().get("valid"):
            print(response.content)
            self.user = response.json().get("username")
        else:
            raise ValueError("Invalid API Key")

    def get_url_for_app(self, app_name):
        endpoint = f"{self.upload_url}/get_app_url"
        payload = {"app_name": app_name, "api_key": self.api_key}
        response = requests.post(endpoint, json=payload)

        if response.status_code == 200:
            return response.json().get("url")
        else:
            raise Exception(f"Error getting URL for app: {response.text}")

    def get_and_update_openapi(self, app_url):
        # Fetch the OpenAPI specification from the deployed app
        openapi_url = f"{app_url}/openapi.json"
        response = requests.get(openapi_url)

        if response.status_code != 200:
            raise Exception(f"Failed to fetch OpenAPI spec: {response.text}")

        openapi_spec = response.json()

        # Add the servers field to the OpenAPI spec
        openapi_spec["servers"] = [{"url": app_url}]

        return openapi_spec

    def deploy_project(self, app_name: str) -> DeploymentResponse:
        repo_url = f"https://github.com/OWigginsHay/{app_name}.git"
        # Create a temporary directory to clone the repository
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                # Clone the repository to the temporary directory

                repo = Repo.clone_from(repo_url, temp_dir)

                # Copy the user's project files to the cloned repository
                project_path = os.path.abspath(".")
                for item in os.listdir(project_path):
                    if item != ".git":
                        src_path = os.path.join(project_path, item)
                        dst_path = os.path.join(temp_dir, item)
                        if os.path.isfile(src_path):
                            shutil.copy(src_path, dst_path)
                        else:
                            shutil.copytree(src_path, dst_path)

                # Stage all changes
                repo.git.add(all=True)

                # Commit the changes
                repo.index.commit("Update project files")

                # Push the changes to the repository
                origin = repo.remote(name="origin")
                origin.push()

                # Trigger the build and deployment process
                build_id = self._trigger_cloud_build(app_name)
                self._wait_for_build_completion(build_id)
                deploy_response = self._deploy_to_cloud_run(app_name)

                app_url = self.get_url_for_app(app_name)
                return DeploymentResponse(
                    message="Deployment successful", url=app_url, build_id=build_id
                )
        except git.exc.GitCommandError as e:
            if "repository not found" in str(e).lower():
                print(
                    "Deployment failed. The specified GitHub repository does not exist.",
                    f"To deploy your project, follow these steps:\n"
                    f"1. Create a new repository on GitHub with the name '{app_name}'.\n"
                    f"2. Push your local project code to the newly created repository.\n"
                    f"3. Run the deployment command again.",
                )
                raise Exception("No Repo")
            else:
                raise e

    # Method to trigger cloud build and return the build_id
    def _trigger_cloud_build(self, app_name, unique_stamp):
        print(
            f"Begin Cloud Build: {app_name}, API Key: {self.api_key}, Stamp: {unique_stamp}"
        )

        trigger_build_endpoint = f"{self.upload_url}/trigger_build"
        response = requests.post(
            trigger_build_endpoint,
            json={"app_name": app_name, "api_key": self.api_key, "stamp": unique_stamp},
        )
        if response.status_code == 200:
            print(response.content)
            return response.json().get("build_id")
        else:
            print(response.content)
            raise Exception("Failed to trigger cloud build.")

    # Method to wait for the build completion
    def _wait_for_build_completion(self, build_id):
        print(f"Wait for Cloud Build: Build ID: {build_id}")
        check_status_endpoint = f"{self.upload_url}/check_build_status/{build_id}"
        while True:
            response = requests.get(check_status_endpoint)
            if response.status_code == 200:
                build_status = response.json().get("build_status")
                if build_status not in ["QUEUED", "WORKING"]:
                    return build_status
            else:
                raise Exception("Failed to check build status.")
            time.sleep(10)  # Wait for 10 seconds before polling again

    # Method to deploy to Cloud Run
    def _deploy_to_cloud_run(self, app_name, unique_stamp):
        self.app.title = app_name
        deploy_endpoint = f"{self.upload_url}/deploy_to_cloud_run"
        payload = {"app_name": app_name, "api_key": self.api_key, "stamp": unique_stamp}
        print(f"Sending payload: {payload}")  # Debugging print statement
        response = requests.post(deploy_endpoint, json=payload)
        if response.status_code != 200:
            raise Exception("Failed to deploy to Cloud Run.")

    def _clean_requirements(self, requirements_path):
        from packaging import version

        with open(requirements_path, "r") as file:
            lines = file.readlines()

        # Keep track of packages
        packages = {}
        for line in lines:
            line = line.strip()  # Remove leading/trailing whitespace
            if "==" in line:
                package, ver = line.split("==")
                if package in packages:
                    # Use packaging.version to compare semantic versions
                    if version.parse(ver) > version.parse(
                        packages[package].split("==")[1]
                    ):
                        packages[package] = f"{package}=={ver}"
                else:
                    packages[package] = line
            elif ">=" in line:
                package, ver = line.split(">=")
                packages[package] = line  # Assume >= specifications do not conflict

        # Write cleaned requirements back to file
        with open(requirements_path, "w") as file:
            for line in packages.values():
                file.write(line + "\n")

    def _generate_requirements(self, project_path: str):
        try:
            subprocess.check_call(["pipreqs", project_path, "--force"])
            requirements_path = os.path.join(project_path, "requirements.txt")
            with open(requirements_path, "a") as file:
                file.write("uvicorn>=0.25.0\n")
            self._clean_requirements(requirements_path)  # Call the cleanup function
            print("requirements.txt generated and cleaned at:", project_path)
        except subprocess.CalledProcessError as e:
            print("An error occurred while generating requirements.txt:", e)

    def _zip_project_directory(self, project_path, zip_file):
        zip_path = os.path.join(project_path, zip_file)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(project_path):
                for file in files:
                    if file != zip_file:  # Exclude the zip file itself
                        file_path = os.path.join(root, file)
                        relative_path = os.path.relpath(
                            file_path, project_path
                        )  # Get relative path
                        zipf.write(file_path, relative_path)
        return zip_path

    def _generate_dockerfile(self, project_path):
        main_module_path = os.path.splitext(
            os.path.basename(sys.modules["__main__"].__file__)
        )[0]
        module_name = main_module_path.replace(
            ".py", ""
        )  # Ensure .py is removed, adjust as necessary
        python_version = (
            f"{sys.version_info.major}.{sys.version_info.minor}"  # Get Python version
        )
        dockerfile_content = f"""
FROM python:{python_version}-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt uvicorn google-cloud-storage
RUN uvicorn --version
RUN echo $PATH && which uvicorn 
COPY . .
CMD ["/usr/local/bin/uvicorn", "{module_name}:app", "--host", "0.0.0.0", "--port", "8080"]
"""
        with open(os.path.join(project_path, "Dockerfile"), "w") as f:
            f.write(dockerfile_content)
        print("Dockerfile generated at:", project_path)

    def _upload_project(self, zip_path) -> Response:
        print("Begin: Uploading Project")
        endpoint = f"{self.upload_url}/upload_zip"

        # Prepare a default response
        default_response = Response()
        default_response.status_code = 500  # Internal Server Error
        default_response._content = b"Failed to upload due to an internal error"

        # Open the file in binary mode
        try:
            with open(zip_path, "rb") as f:
                multipart_form_data = {
                    "file": (os.path.basename(zip_path), f),
                    "api_key": (None, self.api_key),
                }
                response = requests.post(endpoint, files=multipart_form_data)
                return response
        except Exception as e:
            print(f"An error occurred during upload: {e}")
            return default_response

    def create_endpoint(
        self, func: Callable[..., T], methods: List[str] = ["POST"], route: str = None
    ):
        endpoint_route = route or f"/{func.__name__}"
        params = inspect.signature(func).parameters
        type_hints = get_type_hints(func)
        # Right before the if-else block that checks for a specific Pydantic model
        logging.info(
            f"Creating endpoint for {func.__name__}. Checking for specific Pydantic model..."
        )
        model_type = None
        # Check if the function expects a specific Pydantic model
        if any(issubclass(param.annotation, BaseModel) for param in params.values()):
            model_type = next(
                (
                    param.annotation
                    for param in params.values()
                    if issubclass(param.annotation, BaseModel)
                ),
                None,
            )
            logging.info(
                f"Specific Pydantic model found for {func.__name__}: {model_type}"
            )

            async def model_wrapper(body: model_type = Body(...)):
                func_params = inspect.signature(func).parameters
                body_param_name = next(
                    iter(func_params.keys())
                )  # Assuming the first parameter is the model
                logging.info(
                    f"Function {func.__name__} signature: {func_params}. First param: {body_param_name}"
                )
                logging.info(f"Body content for {func.__name__}: {body}")
                logging.info(f"Calling {func.__name__} with body: {body}")
                reult = await func(body)
                logging.info(f"Method {func.__name__} completed with output: {reult}")
                return GenericResponseModel(data=reult)

        else:
            # Dynamically create a Pydantic model based on function parameters
            fields = {
                name: (type_hint, ...)
                for name, type_hint in type_hints.items()
                if name != "return" and type_hint is not inspect.Parameter.empty
            }
            model_type = create_model(f"{func.__name__}RequestModel", **fields)
            logging.info(
                f"No specific Pydantic model found for {func.__name__}. Creating dynamic model..."
            )

            async def model_wrapper(body: model_type = Body(...)):
                # Convert Pydantic model to dict and unpack as function arguments
                model_dict = body.dict()
                logging.info(f"Calling {func.__name__} with body: {body}")
                return GenericResponseModel(data=await func(**model_dict))

        # @wraps(func)
        # async def wrapped_func(body: model_type = Body(...)):
        #     return await model_wrapper(body)

        # Register the endpoint with FastAPI
        for method in methods:
            route_decorator = getattr(self.app, method.lower())
            route_decorator(endpoint_route, response_model=GenericResponseModel)(
                model_wrapper
            )

        return func

    def list_routes(self):
        for route in self.app.routes:
            if isinstance(route, APIRoute):
                print(
                    f"Route: {route.path}, Name: {route.name}, Methods: {route.methods}"
                )

    def endpoint(self, methods: List[str] = ["POST"]):
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Your existing logic here
                return await func(*args, **kwargs)

            # Here we directly use func.__name__ as the route if not provided
            self.create_endpoint(func, methods)
            return wrapper

        return decorator


import base64


class CloudDelivery:
    @staticmethod
    def get_api_key():
        # Retrieve the user ID from an environment variable
        return os.getenv("API_KEY")

    @staticmethod
    def data_from_image(img_path):
        """Encodes image data to a base64 string."""
        with open(img_path, "rb") as image_file:
            img_data = image_file.read()
        return base64.b64encode(img_data).decode()

    @staticmethod
    def data_from_file(file_path):
        """Encodes file data to a base64 string."""
        with open(file_path, "rb") as file:
            file_data = file.read()
        return base64.b64encode(file_data).decode()

    @staticmethod
    def image(img_path):
        if CloudDelivery.is_running_in_cloud():
            # Defaulting to dynamic and public for CDN purposes
            dynamic = True
            make_public = True

            url = CloudDelivery.upload_file_to_gcp(img_path, dynamic, make_public)
            return url
        else:
            # Mock implementation for local testing or alternative handling
            return CloudDelivery.mock_upload(img_path)

    @staticmethod
    def is_running_in_cloud():
        # Check for an environment variable that's only set in your cloud environment
        return os.getenv("RUNNING_IN_CLOUD") is not None

    @staticmethod
    def make_object_public(bucket_name: str, blob_name: str):
        """
        Makes a GCS object publicly accessible via an Intermediary Server (IS).

        :param api_key: The API key for authenticating with the IS.
        :param bucket_name: The name of the GCS bucket.
        :param blob_name: The name of the blob within the GCS bucket.
        :param upload_url: The base URL of the Intermediary Server.
        """
        endpoint = f"https://intermediary-server-service-4dvqi5ecwa-nw.a.run.app/make_object_public"
        payload = {
            "api_key": CloudDelivery.get_api_key(),
            "bucket_name": bucket_name,
            "blob_name": blob_name,
        }
        response = requests.post(endpoint, json=payload)

        if response.status_code == 200:
            print(
                f"Blob {blob_name} in {bucket_name} is now publicly accessible via IS."
            )
        else:
            print(f"Failed to make the blob publicly accessible: {response.text}")

    @staticmethod
    def upload_file_to_gcp(
        file_path: str, dynamic: bool = False, make_public: bool = False
    ) -> str:
        """
        Uploads a file to GCP and returns its public URL.

        :param file_path: Path to the file to upload.
        :param file_type: Type of the file (e.g., 'csv', 'pdf', 'xlsx').
        :param dynamic: Whether the blob name should be generated dynamically.
        :param make_public: Whether the uploaded file should be made public.
        :return: Public URL of the uploaded file.
        """
        upload_endpoint = "https://intermediary-server-service-4dvqi5ecwa-nw.a.run.app/upload_file_to_gcp"
        file_data = CloudDelivery.data_from_file(file_path)
        payload = {
            "api_key": CloudDelivery.get_api_key(),
            "file_data": file_data,
            "file_name": file_path,
            "dynamic": dynamic,
            "make_public": make_public,
        }
        response = requests.post(upload_endpoint, json=payload)
        if response.status_code == 200:
            return response.json().get("public_url")
        else:
            logging.error(f"Failed to upload file: {response.text}")
            raise Exception("Failed to upload file")

    @staticmethod
    def download_file_from_gcp(local_save_path: str) -> bool:
        # Define the download and clean endpoints
        download_endpoint = "https://intermediary-server-service-4dvqi5ecwa-nw.a.run.app/download_file_from_gcp"
        clean_endpoint = (
            "https://intermediary-server-service-4dvqi5ecwa-nw.a.run.app/clean_file"
        )

        # Prepare the payload for the download request
        payload = {
            "api_key": CloudDelivery.get_api_key(),  # Replace with actual method to retrieve API key
            "file_identifier": os.path.basename(
                local_save_path
            ),  # Assuming file_identifier is the basename
        }

        try:
            # Send the request to download the file
            download_response = requests.post(download_endpoint, json=payload)

            # Check if the file was downloaded successfully
            if download_response.status_code == 200:
                # Save the file
                with open(local_save_path, "wb") as file:
                    file.write(download_response.content)
                logging.info(
                    f"File successfully downloaded and saved to {local_save_path}."
                )

                # Extract the temporary file name from the response headers
                temp_file_name = download_response.headers.get("X-Temp-File-Name")

                # Clean up the temporary file on the server
                if temp_file_name:
                    clean_payload = {"temp_file_name": temp_file_name}
                    clean_response = requests.post(clean_endpoint, json=clean_payload)

                    if clean_response.status_code == 200:
                        logging.info(
                            "Temporary file deleted successfully on the server."
                        )
                    else:
                        logging.warning(
                            "Failed to delete the temporary file on the server."
                        )
                return True
            else:
                logging.error(f"Failed to download the file: {download_response.text}")
                return False
        except Exception as e:
            logging.error(f"Exception occurred: {str(e)}")
            return False

    @staticmethod
    def mock_upload(img_data):
        # Mock upload logic for local testing
        # You can use Python's 'mock' library or a simple placeholder
        return "https://mockurl.com/image_url"
