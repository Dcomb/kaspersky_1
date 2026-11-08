# Инференс LLM на CPU с vLLM и Kubernetes

Проект запускает открытую instruct-модель `Qwen/Qwen2.5-0.5B-Instruct` через vLLM 0.27.0 **строго на CPU** в Minikube. Отдельный непривилегированный initContainer скачивает зафиксированную ревизию модели в PersistentVolumeClaim (PVC). Основной контейнер загружает модель из этого тома в офлайн-режиме. Оба контейнера работают с UID 6767. Все Python-зависимости, включая транзитивные, закреплены в `requirements.txt` и `requirements-downloader.txt`.

API требует Bearer-токен. Middleware проверяет его для всех маршрутов, кроме `/health`, и записывает только метод, путь, HTTP-статус и длительность запроса. Заголовки, промпты, ответы модели и параметры URL в журнал не попадают. Стандартное логирование запросов и ответов vLLM, а также access log Uvicorn отключены.

## Требования к окружению

- Docker с Linux-контейнерами и Minikube. В Windows нужен Docker Desktop с движком WSL2. Отдельная установка `kubectl` необязательна: Minikube предоставляет клиент подходящей версии.
- CPU x86_64 с AVX2 или новее. Для Minikube в примере выделены 4 ядра, 6500 МиБ RAM и диск 25 ГиБ. Основной контейнер запрашивает 2 ГиБ и ограничен 5 ГиБ памяти. При доступных около 8 ГБ для Docker запас памяти небольшой.
- Интернет для сборки образов и первой загрузки модели. Повторные запуски используют PVC.

Идентификатор и полная 40-символьная ревизия модели указаны в `k8s/configmap.yaml`. Для другой модели измените `HF_MODEL_ID` и `HF_REVISION`. Закрытая модель дополнительно потребует токен Hugging Face. CPU-образ предварительно загружает Intel OpenMP (`libiomp5.so`) из закреплённого набора зависимостей.

## Запуск одной командой

Запустите Docker Desktop и убедитесь, что `docker info` работает. Установите Minikube по [официальной инструкции](https://minikube.sigs.k8s.io/docs/start/), если он ещё не установлен. Остановите GPU-контейнер и старый port-forward, если они используют порт 8000. Из корня проекта выполните:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_cpu.ps1
```

Скрипт запускает Minikube, собирает и загружает отсутствующие образы, создаёт Secret, применяет манифесты, поднимает одну реплику, ждёт готовности и открывает port-forward. При повторном запуске он использует уже имеющиеся образы и PVC. Если вы изменили код приложения или зависимости, добавьте `-RebuildImages`. Пересборка может занять много времени и места на диске. Оставьте терминал со скриптом открытым, пока нужен API. `Ctrl+C` останавливает только port-forward.

Чтобы после работы освободить память, не удаляя PVC:

```powershell
minikube kubectl -- scale deployment/inference-api --replicas=0
minikube stop
```

## Ручной запуск

```powershell
minikube start --driver=docker --cpus=4 --memory=6500 --disk-size=25g
function kubectl { minikube kubectl -- $args }
docker build -t vllm-cpu-private:0.1.0 -f Dockerfile .
docker build -t vllm-downloader:0.1.0 -f Dockerfile.downloader .
minikube image load vllm-cpu-private:0.1.0
minikube image load vllm-downloader:0.1.0
```

При первом развёртывании создайте оба токена вне репозитория. Выбранная модель публичная, поэтому файл токена HF может быть пустым. Для закрытой модели заранее запишите в него действующий токен. Файлы с токенами не добавлять в Git.

```powershell
$hfFile = Join-Path $env:TEMP 'hf-token.txt'
$apiFile = Join-Path $env:TEMP 'api-token.txt'
[IO.File]::WriteAllText($hfFile, '')
[IO.File]::WriteAllText($apiFile, ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')))
kubectl create secret generic inference-secrets --from-file="hf-token=$hfFile" --from-file="api-token=$apiFile"
kubectl apply -k k8s/
kubectl rollout status deployment/inference-api --timeout=20m
kubectl port-forward service/inference-api 8000:8000
```

Команда `port-forward` остаётся работающей. В ином терминале из корня проекта можно проверить авторизацию и генерацию:

```powershell
$env:API_TOKEN = [IO.File]::ReadAllText((Join-Path $env:TEMP 'api-token.txt')).Trim()
python scripts/smoke_test.py
```

Ожидаемый вывод: `Authorization and inference: OK`. Скрипт проверяет два случая. Запрос без токена должен получить `401`. Запрос с токеном должен получить `200` и ответ модели. Для диагностики используйте `kubectl get pods`, `kubectl logs deployment/inference-api -c model-download` и `kubectl logs deployment/inference-api -c vllm`.

## Повторный запуск без скачивания модели

После первого успешного запуска перезапустить Pod, сохранив PVC:

```powershell
kubectl rollout restart deployment/inference-api
kubectl rollout status deployment/inference-api --timeout=20m
kubectl logs deployment/inference-api -c model-download
python scripts/smoke_test.py
```

В логе загрузчика должно появиться сообщение, что модель уже есть на PVC и скачивание пропущено. Если маркер и файлы модели на месте, `download_model.py` не вызывает `snapshot_download`. Основной контейнер загружает модель из `/models/<revision>` с переменными `HF_HUB_OFFLINE=1` и `TRANSFORMERS_OFFLINE=1`. Чтобы проверить отсутствие сетевых запросов, можно запретить Pod выход в интернет и повторить рестарт со smoke-тестом. Это работает только в кластере, где CNI применяет NetworkPolicy. Во время проверки сохраняйте тот же PVC. При его удалении кэш может пропасть в зависимости от `reclaimPolicy` тома.

## Изменение настроек инференса

Измените `k8s/configmap.yaml`, затем примените настройки и перезапустите Pod:

```powershell
kubectl apply -k k8s/
kubectl rollout restart deployment/inference-api
```

Пересобирать образ не нужно. Значение `VLLM_CPU_KVCACHE_SPACE` задаётся в ГиБ. Увеличивайте его только при наличии памяти для весов модели, процессов Python и KV-кэша. Меньший контекст и меньшее число одновременных последовательностей снижают потребление памяти. `VLLM_CPU_NUM_OF_RESERVED_CPU` позволяет оставить ядро для API-фронтенда.

## Нагрузочный тест CPU

При работающем port-forward и установленном `API_TOKEN` выполните два прогона:

```powershell
python scripts/benchmark.py --requests 20 --concurrency 1 --max-tokens 32
python scripts/benchmark.py --requests 20 --concurrency 2 --max-tokens 32
```

Скрипт отправляет короткие и длинные промпты. Перед каждым промптом он добавляет уникальный префикс, чтобы повторный запрос не использовал тот же кэш. В результатах указаны число успешных запросов и ошибок, TTFT p50/p95, полная задержка p50/p95, запросы/с и выходные токены/с. TTFT измеряется от отправки запроса до первого непустого фрагмента ответа. Перед нагрузочным тестом запустите smoke-тест для прогрева модели.

Фактические результаты на ноутбуке с четырьмя ядрами, моделью Qwen2.5-0.5B-Instruct и максимумом 32 выходных токена, по 20 запросов на каждую строку:

| Промпт | Одновременных запросов | Успешно / ошибок | TTFT p50 / p95 | Задержка p50 / p95 | Запросов/с | Выходных токенов/с |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Короткий | 1 | 20 / 0 | 2,203 / 2,377 с | 6,406 / 6,881 с | 0,161 | 5,141 |
| Длинный | 1 | 20 / 0 | 7,047 / 7,313 с | 11,235 / 11,921 с | 0,089 | 2,832 |
| Короткий | 2 | 20 / 0 | 7,734 / 8,516 с | 11,609 / 12,918 с | 0,170 | 5,437 |
| Длинный | 2 | 20 / 0 | 18,242 / 18,817 с | 22,391 / 23,510 с | 0,089 | 2,854 |

Длинный промпт требует больше времени на обработку входного текста, поэтому TTFT выше. При `VLLM_MAX_NUM_SEQS=1` запросы выполняются по одному, а второй ждёт своей очереди. Скорость коротких запросов выросла с 0,161 до 0,170 запросов/с. Скорость длинных осталась около 0,089 запросов/с. Задержка при этом заметно выросла. Во время теста Pod работал без перезапусков. Minikube использовал 5,212 из 6,348 ГиБ памяти и примерно четыре ядра CPU. p95 рассчитан по 20 запросам, поэтому не стоит считать его гарантией для других нагрузок.

**Много коротких запросов.** На машине с большим запасом памяти стоит сравнить более высокие `VLLM_MAX_NUM_SEQS` и `VLLM_MAX_NUM_BATCHED_TOKENS`, наблюдая за p95 и RAM. На данном ноутбуке ограничение в одну последовательность безопаснее сохранить.

**Меньше запросов с большим контекстом.** Сначала уберите ненужный входной текст. Если будущие промпты превысят текущий бюджет пакетной обработки, попробуйте увеличить `VLLM_MAX_NUM_BATCHED_TOKENS`. Для этого потребуются свободная память и CPU. Увеличивайте `VLLM_MAX_MODEL_LEN` только тогда, когда нужен больший контекст. Это может увеличить расход памяти на KV-кэш. На четырёх ядрах параллельные запросы почти не повышают скорость.

## Необязательный эксперимент: GPU в Windows

**Обязательное решение выше работает только на CPU.** Отдельный `scripts/run_gpu.ps1` запускает ту же модель напрямую в Docker Desktop с официальным CUDA-образом vLLM 0.27.0. Он использует тот же API-токен и middleware, работает от непривилегированного пользователя, открывает API только на `127.0.0.1:8000` и сохраняет модель в `models/gpu-hf-cache`. Это не Kubernetes и не PVC из основного решения. В WSL2 выбран Model Runner V1: для V2 может быть недоступен UVA.

Остановите CPU-бенчмарк и port-forward, уменьшите число реплик до нуля и остановите Minikube перед запуском GPU. CUDA-образ большой: перед первой загрузкой скрипт требует не менее 30 ГиБ свободного места и предупреждает, если доступно меньше 45 ГиБ. Контейнер ограничен 6 ГиБ RAM и использует целевой предел в 50% видеопамяти.

```powershell
kubectl scale deployment/inference-api --replicas=0
minikube stop
powershell -ExecutionPolicy Bypass -File scripts/run_gpu.ps1
```

После готовности API во втором терминале:

```powershell
$env:API_TOKEN = [IO.File]::ReadAllText((Join-Path $env:TEMP 'api-token.txt')).Trim()
python scripts/smoke_test.py
python scripts/benchmark.py --requests 6 --concurrency 1 --max-tokens 64
```

Исторический результат на RTX 4060 Laptop GPU, по 6 запросов на сценарий, максимум 64 выходных токена:

| Промпт | Успешно / ошибок | TTFT p50 / p95 | Задержка p50 / p95 | Запросов/с | Выходных токенов/с |
| --- | ---: | ---: | ---: | ---: | ---: |
| Короткий | 6 / 0 | 0,047 / 0,129 с | 0,414 / 0,601 с | 2,220 | 142,064 |
| Длинный | 6 / 0 | 0,047 / 0,074 с | 0,414 / 0,449 с | 2,385 | 152,623 |

Эти GPU-цифры получены **до** добавления уникальных префиксов в бенчмарк. Тогда внутри сценария повторялся один промпт, и кэш префикса мог ускорить тест. Повторный запуск текущей версии скрипта не обязан воспроизвести таблицу. GPU-замер нельзя подставлять вместо результата CPU в Kubernetes. Остановите GPU-контейнер через `Ctrl+C` в его терминале.

## Зависимости и безопасность

Файлы с зафиксированными версиями были созданы для Linux x86_64 и Python 3.12 через `uv`:

```powershell
uv pip compile requirements.in --python-version 3.12 --python-platform x86_64-manylinux_2_34 --torch-backend cpu --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match --output-file requirements.txt
uv pip compile requirements-downloader.in --python-version 3.12 --python-platform x86_64-manylinux_2_34 --output-file requirements-downloader.txt
```

URL CPU-колеса vLLM в `requirements.in` закрепляет релиз 0.27.0. После изменения зависимостей пересоберите и проверьте оба образа. Service имеет тип `ClusterIP`. `port-forward` нужен для локального доступа. Для публичного доступа понадобятся TLS-прокси или Ingress и сетевые ограничения кластера. Маршрут `/health` открыт для Kubernetes-проб. Остальные маршруты требуют API-токен. Kubernetes Secrets могут храниться на диске без шифрования, если в кластере не настроено encryption at rest. Не добавляйте файлы токенов в Git и ограничьте доступ к кластеру.
