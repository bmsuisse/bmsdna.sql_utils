from faker import Faker
from datetime import date, datetime, timezone
import pandas as pd
from deltalake import write_deltalake, WriterProperties


def create_test_data():
    fake = Faker(["it_IT", "de-DE", "fr-FR", "en_US"])
    res = []
    for i in range(1, 10000):
        lat, lon = fake.latlng()
        obj = {
            "id": i,
            "name": fake.name(),
            "address": fake.address(),
            "text": fake.text(),
            "nbr": fake.pyfloat(),
            "inie": fake.pyint(),
            "date": date.fromisoformat(fake.date()),
            "datetime_ntz": fake.date_time(),
            "datetime_tz": fake.date_time().astimezone(timezone.utc),
        }
        res.append(obj)
    write_deltalake("tests/data/faker", pd.DataFrame(res), writer_properties=WriterProperties(compression="ZSTD"))


if __name__ == "__main__":
    create_test_data()
