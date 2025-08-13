FROM mysterysd/wzmlx:latest

WORKDIR /usr/src/app
RUN chmod 777 /usr/src/app

COPY requirements.txt .
RUN pip3 install --upgrade setuptools wheel
RUN pip3 install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y openjdk-17-jre-headless

COPY . .

CMD ["bash", "start.sh"]
