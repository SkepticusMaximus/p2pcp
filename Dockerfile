# A headless p2pcp node — sell/buy CompuCoin compute on any server.
#
#   docker build -t p2pcp .
#   docker run --rm -p 9000:9000 p2pcp serve --host 0.0.0.0 --port 9000
#   docker run --rm p2pcp buy "job" --host <ip> --port 9000
#
# Persist identity + earnings across restarts by mounting a volume and using
# --keyfile:  -v p2pcp-data:/data  ... serve --keyfile /data/node.key
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY p2pcp ./p2pcp
RUN pip install --no-cache-dir .

# `p2pcp` is the console entry point; args after the image name flow straight to it.
ENTRYPOINT ["p2pcp"]
CMD ["serve", "--host", "0.0.0.0", "--port", "9000"]
