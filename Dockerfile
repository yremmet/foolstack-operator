FROM python:3.10-bullseye
#RUN apt-get update && apt-get install libpq-dev
COPY requirements.txt /
#RUN apt update && apt -y install gnupg2 wget vim && \
#   echo "deb http://apt.postgresql.org/pub/repos/apt bullseye-pgdg main" > /etc/apt/sources.list.d/pgdg.list && \
#   wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add -
#RUN apt -y update && apt install -y postgresql-14

RUN pip install --no-cache-dir -r /requirements.txt
COPY postgres.py /
CMD kopf run /postgres.py --verbose -A