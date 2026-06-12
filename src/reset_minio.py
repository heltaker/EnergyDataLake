import boto3

# Подключаемся к MinIO
s3_client = boto3.client(
    's3',
    endpoint_url="http://localhost:9000",
    aws_access_key_id="minio_admin",
    aws_secret_access_key="minio_password"
)

# Список корзин, которые мы хотим полностью удалить
buckets_to_delete = ['processed-data', 'processed-datasets', 'raw-uploads']

for bucket in buckets_to_delete:
    try:
        print(f"--- Очистка корзины: {bucket} ---")
        # 1. Получаем список всех файлов в корзине
        objects = s3_client.list_objects_v2(Bucket=bucket)

        # 2. Если файлы есть, удаляем их по одному
        if 'Contents' in objects:
            for obj in objects['Contents']:
                s3_client.delete_object(Bucket=bucket, Key=obj['Key'])
                print(f"Удален файл: {obj['Key']}")

        # 3. Когда корзина пуста, удаляем её
        s3_client.delete_bucket(Bucket=bucket)
        print(f"Корзина '{bucket}' успешно удалена!\n")

    except Exception as e:
        print(f"Пропуск (возможно корзина уже удалена или не существует): {e}\n")

print("Сброс MinIO завершен!")