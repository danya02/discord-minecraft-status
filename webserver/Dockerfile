FROM python:3.9-slim

EXPOSE 8000
ENTRYPOINT ["gunicorn", "main:app", "-w 2", "--threads 2", "-b 0.0.0.0:8000"]

WORKDIR /
COPY requirements.txt /
RUN pip3 install -r /requirements.txt

COPY main.py /
