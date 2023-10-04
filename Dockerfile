FROM python:3.12-alpine

COPY requirements.txt /tmp
RUN pip install -r /tmp/requirements.txt

COPY . /app
WORKDIR /app

ENV PYTHONPATH "${PYTHONPATH}:/app"

CMD ["python", "-u", "src/rfxtrx2mqtt.py"]
