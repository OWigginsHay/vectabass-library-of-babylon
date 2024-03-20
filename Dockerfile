
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y git
RUN pip install --no-cache-dir -r requirements.txt uvicorn google-cloud-storage
RUN uvicorn --version
RUN echo $PATH && which uvicorn 
COPY . .
CMD ["/usr/local/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
