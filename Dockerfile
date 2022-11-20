FROM python:slim
COPY requirements.txt /instaling/
WORKDIR /instaling
RUN pip install -r requirements.txt
COPY automatic.py interactive.py scheduled.py /instaling/
COPY libs /instaling/libs
CMD ["python", "scheduled.py"]