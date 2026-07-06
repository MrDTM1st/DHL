FROM python:3.12-slim
WORKDIR /app
COPY region2-emailer/cloud/server.py .
ENV PORT=8080
EXPOSE 8080
CMD ["python", "server.py"]
