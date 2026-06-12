import pandas as pd
import boto3
import io
from sqlalchemy import create_engine, text

# --- НАСТРОЙКИ ---
POSTGRES_URI = "postgresql://admin:secret_password@localhost:5432/energy_lake"
MINIO_URL = "http://localhost:9000"
MINIO_ACCESS_KEY = "minio_admin"
MINIO_SECRET_KEY = "minio_password"

engine = create_engine(POSTGRES_URI)
s3_client = boto3.client(
    's3',
    endpoint_url=MINIO_URL,
    aws_access_key_id=MINIO_ACCESS_KEY,
    aws_secret_access_key=MINIO_SECRET_KEY
)


def get_latest_data(source_name: str) -> pd.DataFrame:
    """
    Функция обращается к PostgreSQL, находит путь к самому свежему файлу
    указанного источника, скачивает его из MinIO и возвращает как DataFrame.
    """
    with engine.connect() as conn:
        # Ищем путь в БД
        query = text("""
            SELECT minio_processed_path 
            FROM data_files f
            JOIN data_sources s ON f.source_id = s.source_id
            WHERE s.source_name = :source_name
            ORDER BY processed_at DESC 
            LIMIT 1
        """)
        result = conn.execute(query, {"source_name": source_name}).fetchone()

        if not result:
            raise ValueError(f"Данные для источника '{source_name}' не найдены в БД.")

        full_path = result[0]  # Например: processed-data/macro_stats/iea/Export.parquet
        print(f"Найден файл в БД: {full_path}")

        # Разбиваем путь на корзину (bucket) и сам путь к файлу (key)
        bucket, key = full_path.split('/', 1)

        # Скачиваем файл из MinIO прямо в оперативную память
        print("Скачивание из MinIO...")
        response = s3_client.get_object(Bucket=bucket, Key=key)
        parquet_bytes = response['Body'].read()

        # Конвертируем бинарные данные Parquet обратно в Pandas DataFrame
        df = pd.read_parquet(io.BytesIO(parquet_bytes))
        print(f"Данные успешно загружены! Размер: {df.shape}")

        return df


if __name__ == "__main__":
    # Тестируем коннектор
    print("=== Тест извлечения данных GEM ===")
    df_gem = get_latest_data('Global Energy Monitor')

    # Выведем список первых 15 колонок, чтобы узнать их точные названия
    print("Доступные колонки GEM:", df_gem.columns.tolist()[:15])

    # Выводим первые 3 строки и первые 5 колонок, чтобы посмотреть на сами данные
    print(df_gem.iloc[:, :5].head(3))

    print("\n=== Тест извлечения данных IEA ===")
    df_iea = get_latest_data('IEA')

    print("Доступные колонки IEA:", df_iea.columns.tolist()[:10])
    print(df_iea.iloc[:, :5].head(3))