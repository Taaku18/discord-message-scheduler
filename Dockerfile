FROM python:3.9-slim as py

RUN apt update && apt install -y g++

FROM py as build

COPY requirements.txt /
RUN pip install --prefix=/inst -U -r /requirements.txt

FROM py

COPY --from=build /inst /usr/local

WORKDIR /bot
CMD ["python", "start.py"]
COPY . /bot
