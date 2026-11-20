FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 tea \
    && useradd --uid 10001 --gid tea --no-create-home tea \
    && install -d -o tea -g tea /data
COPY tea ./tea
USER tea
EXPOSE 8080
CMD ["waitress-serve", "--listen=0.0.0.0:8080", "--threads=8", "--max-request-body-size=32768", "--call", "tea.app:create_app"]
