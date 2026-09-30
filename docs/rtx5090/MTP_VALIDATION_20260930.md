# Qwen3.8 Flash Next: проверка MTP, PLE rollback и ускорений

Эксперимент начат 2026-09-30. Отчёт обновлён 2026-10-01 по завершённым
20 screening- и 12 confirmation-прогонам. **Значительное стабильное ускорение
не подтверждено: lookup/reuse не переносим в main. Отдельно принято полезное
исправление PLE rollback с регрессионными тестами.** Для новой сборки только
с этим runtime-исправлением отдельный test suite завершился: **181 passed,
48 skipped, 2 deselected**. Новый сервис запущен и проверен: warmup завершён,
**9/9 semantic и 4/4 API checks прошли**. Runtime подтверждён на `f56cf78`;
этот commit опубликован в GitHub main, удалённый ref проверен через `git ls-remote`.

## Что уже установлено

- Пропущенный откат PLE convolution history воспроизведён регрессионным тестом
  на исходном main. В экспериментальной версии прошли CPU и CUDA graph проверки;
  отдельно новый main прошёл собственную test suite после исправления
  изоляции CPU RoPE cache в тестовой fixture, без изменения runtime. Его
  собственные semantic/API проверки и готовность сервиса также подтверждены.
- На более длинных ответах T1 **PLE fix + reuse** дал **32.564 против 31.917 tok/s
  (+2.03%)**, по три ответа по 1024 токена; диапазоны пересекаются. Начальные
  +8% на двух ответах по 512 токенов не повторились как столь же большой
  выигрыш. В source editing прирост этого же профиля составил только **+0.89%**.
  Это сравнение с прежним main, не изолированный эффект reuse и не измеренная
  скорость новой сборки только с PLE fix.
- Baseline, reuse и lookup прошли по 9/9 ограниченных semantic cases. У reuse также
  прошли 240077-token retrieval, Vision, tool call и Responses. Ошибок в этих
  случаях не найдено; общее качество модели этим не доказано.
- Prompt lookup не ускорил задачу объяснения большого фрагмента кода и
  оказался **на 4.26% медленнее baseline при source editing**: 41.168 против
  43.002 tok/s. Корректный выданный префикс не сопровождался выигрышем скорости.
- Квантизация NVFP4, BF16 KV и резерв контекста 262144 не уменьшались. Эти
  условия сами по себе **не доказывают сохранение общего качества модели**.

## Исходники и условия

| Компонент | Зафиксированное значение |
|---|---|
| Исторический baseline main | `9ef483c47d805e267d7926c2f1ca9eb439cbaf64` |
| Исторический experimental candidate runtime | `735ec887578192e3f609357b3868f3191ca75a25` |
| Дополнительные тесты и semantic harness | `3de1055641e872e8d894c067288fabd79006d86e` |
| Source-edit fixture | `6218f6cb827662553d2eca6c4481d617e6505db8` |
| Проверенный новый main, без lookup/reuse | `f56cf78cefbb931079f114de5368e2596034ab3b`; tests, serving validation и deployment подтверждены |
| PLE runtime fix в новом main | `7d296eced5bd3f388ebf325c3300172383318b34` |
| Изоляция тестового CPU RoPE cache | `f56cf78cefbb931079f114de5368e2596034ab3b`; только test fixture |
| Машина | VM5200, RTX 5090 32 GiB, PCIe 3.0 x16 |
| CPU / RAM | 32 vCPU, 160 GiB, NUMA0; host E5-2698 v4, DDR4 2133 MT/s |
| Драйвер в screen evidence | 595.91.07 |
| Модель | `RadixArk/Qwen3.8-Flash-Next-NVFP4`, API ID `qwen38-flash-next` |
| Фактический вход / выход | **104869 / 512 токенов** в каждом screening-запросе |
| Окно / KV | 262144 токена зарезервировано, BF16; это не заполнение 262K |
| MTP / параллелизм | MTP3; C=1, последовательные запросы |
| Sampling | temperature 0 и 1; reasoning effort `medium`; `ignore_eos=true` |
| MoE | hybrid, 12 CPU workers, auto cache, memory ratio 0.87 |
| Prefill / PLE | chunk 14336, mixer 2, D2D; pinned PLE |
| Startup cache plan | 3325 expert slots / 8.59 GiB; KV 6.71 GiB |

В историческом эксперименте исходники тестов добавлены поверх candidate без
изменения runtime после `735ec88`. Три неизменённых native extensions (`_cpu_moe`, `_pinned_tensor`,
`_ple_store`) перенесены из рабочего окружения; SHA256 каждой пары совпал.
Screen fixture: [real-code-prompt.txt.gz](../../benchmarks/rtx5090/fixtures/real-code-prompt.txt.gz),
SHA256 `86c5ebe3fd35fe8a934ec41fdab6cab2d57252c9a9f93d641d32498575e699be`.
Он просит объяснить перекрытие CPU expert computation, GPU работы и PCIe transfers
по предоставленным исходникам, включая точки синхронизации и псевдокод.

Перед каждым screening-профилем сервис запускался заново и проходил одинаковый warmup.
Порядок профилей: base, fixed, lookup, reuse, both; внутри каждого T0, затем T1.
Это последовательный screening, а не рандомизированный статистический эксперимент.
По сохранённому аудиту HTTP-логов внешних generation-запросов во время этих
профилей не было. После screen рабочая конфигурация была восстановлена и
прогрета; confirmation затем снова временно переключал конфигурации.

Следующая таблица описывает исторические измеренные профили. Lookup/reuse
runtime-кода нет в новом main; включение этих переменных там не воспроизводит
экспериментальные профили.

| Профиль | Runtime | `FT_SPEC_LOOKUP` | `FREETOKEN_HYBRID_FETCH_REUSE` | PLE rollback |
|---|---|---:|---:|---|
| base | исходный main | 0 | 0 | отсутствует в исходном коде |
| fixed | candidate | 0 | 0 | включён |
| lookup | candidate | 1 | 0 | включён |
| reuse | candidate | 0 | 1 | включён |
| both | candidate | 1 | 1 | включён |

Драйвер задавал `FT_SPEC_PLE_ROLLBACK=1` всем профилям; исходный main не читает
этот новый флаг. `fixed` отделяет исправление корректности от включения новых
скоростных флагов. Сравнение с base не является проверкой побитового совпадения:
baseline содержит обнаруженный дефект PLE, а переназначение CPU/GPU может
менять последние биты арифметики. Сравнения `reuse`, `lookup` или `both` с
`base` включают также PLE fix: ими нельзя изолировать эффект одного флага.

## Результаты screening

Скорость decode: `(completion_tokens - 1) / (last_token_time - first_token_time)`.
Учитывается первый непустой content/reasoning/tool delta, а не SSE metadata.
В скобках дан наблюдавшийся минимум и максимум, **не доверительный интервал**.
В каждой ячейке два прогона. Потоковая передача может выдавать несколько
принятых MTP токенов почти одновременно, поэтому interval отдельного chunk не
следует интерпретировать как время вычисления одного токена.

| Профиль | T0 decode, tok/s | От base | T1 decode, tok/s | От base |
|---|---:|---:|---:|---:|
| base | 35.132 (34.543–35.721) | — | 32.162 (31.901–32.424) | — |
| fixed | 35.817 (35.213–36.420) | +1.95% | 31.160 (30.276–32.044) | −3.12% |
| lookup | 33.888 (33.211–34.565) | −3.54% | 31.418 (30.877–31.958) | −2.32% |
| reuse | 36.277 (35.899–36.655) | +3.26% | 34.742 (34.498–34.987) | +8.02% |
| both | 33.520 (32.656–34.384) | −4.59% | 32.733 (32.600–32.867) | +1.78% |

| Профиль | Медиана TTFT T0 / T1, с | Медиана end-to-end T0 / T1, tok/s |
|---|---:|---:|
| base | 42.500 / 42.051 | 8.975 / 8.837 |
| fixed | 42.420 / 41.982 | 9.031 / 8.768 |
| lookup | 42.347 / 41.931 | 8.915 / 8.797 |
| reuse | 42.441 / 42.015 | 9.057 / 9.026 |
| both | 42.349 / 41.957 | 8.888 / 8.894 |

End-to-end здесь включает длинный prefill и равен `completion_tokens / elapsed_s`.
Это объясняет, почему +8% decode не означает +8% скорости всего запроса.
Отдельный чистый prefill throughput из этих HTTP-таймингов не измерялся.
Исторические 40–43 tok/s при другом резерве KV и длине ответа не являются
контрольной группой для этой таблицы.

В коротком screening против `fixed` прирост `reuse` при T1 составлял 11.50%:
только это сравнение отделяет включение reuse от PLE fix. При двух повторах
число не является устойчивой оценкой; длинного сравнения `reuse` с `fixed`
не было. Более длинная проверка ниже сравнивает весь профиль PLE fix + reuse
с прежним baseline и не подтвердила столь большой суммарный выигрыш. Комбинация `both` не дала
убедительного преимущества и не выбрана для углублённого этапа.

## Confirmation: baseline, reuse и lookup завершены

Резерв 262144, BF16 KV, NVFP4 и MTP3 сохранены. Baseline использовал уже
восстановленный и прогретый production instance; driver проверил совпадение
health/warmup instance IDs и отсутствие тестового override. Затем отдельно
запущены и прогреты reuse, затем lookup. Это последовательные измерения, без фиксированного
RNG seed и без рандомизации порядка; малое число повторов ограничивает выводы.

| Нагрузка | Профиль | n | Decode median (min–max), tok/s | TTFT median, с | End-to-end median, tok/s |
|---|---|---:|---:|---:|---:|
| Объяснение кода, 104869 input / 1024 output, T1 Medium | base | 3 | 31.917 (31.724–33.415) | 41.971 | 13.806 |
| То же | reuse | 3 | 32.564 (32.164–33.637) | 41.948 | 13.884 |
| Source editing, 11712 input / 1024 output, T0 thinking off | base | 2 | 43.002 (42.904–43.101) | 5.271 | 35.235 |
| То же | reuse | 2 | 43.385 (43.385–43.386) | 5.269 | 35.495 |
| То же | lookup | 2 | 41.168 (41.125–41.212) | 5.657 | 33.571 |

В длинном объяснении разница медиан decode **+2.03%**, с пересечением
наблюдавшихся диапазонов. В редактировании **+0.89%**. Обе разницы относятся
к профилю **PLE fix + reuse против прежнего main**. Скорость будущего main
только с PLE fix ими не измерена. Эти результаты не
подтверждают большой устойчивый выигрыш, достаточный сам по себе для включения
reuse по умолчанию. Короткие +8% остаются результатом screening, а не итогом.

У lookup source editing медленнее baseline на **4.26% (около 4.3%)** и не дал
пользы даже в задаче копирования исходника с малой правкой. По этим измерениям
его дополнительная работа не окупилась. Отдельного профилирования причины
замедления здесь нет; общий вывод о любых других edit-задачах из двух
повторов делать нельзя. Рекомендация для текущей конфигурации: default off.

Во всех шести edit-прогонах выданный префикс побайтно совпал с ожидаемым
исходником и содержал требуемую правку uppercase hex prefix. У всех шести
одинаковый output SHA256. Проверенные candidate-префиксы имеют 3973 символа.
Вывод ограничен 1024 токенами: **это проверка
правильного начала файла с фактической правкой, не полного отредактированного
модуля**. Сгенерированный код не исполнялся.

| Ограниченная functional проверка | Baseline | Reuse | Lookup |
|---|---:|---:|---:|
| [Semantic suite, 9 случаев](../../benchmarks/rtx5090/mtp_quality.py) | 9/9; 54.837 с | 9/9; 54.535 с | 9/9; 55.571 с |
| Retrieval при 240077 input tokens, точные ALPHA/BETA/GAMMA | Не проверялось здесь | Pass; 97.358 с | Не проверялось здесь |
| Красное изображение 1536×1536 | Не проверялось здесь | Pass; 8.472 с | Не проверялось здесь |
| `get_weather` с Moscow | Не проверялось здесь | Pass; 6.491 с | Не проверялось здесь |
| Responses API, READY | Не проверялось здесь | Pass; 1.656 с | Не проверялось здесь |

Semantic suite проверяет JSON edit, арифметику, фильтрацию, output budgets 1–4,
natural EOS и повторный prefix: **27 успешных запусков 9 одинаковых случаев
на трёх профилях**, не 27 разных задач. Extended API suite у reuse прошёл **4/4**.
240K retrieval подтверждает конкретный случай работы с почти заполненным
контекстом; он не измеряет устойчивую decode-скорость на 240K и не доказывает
качество на произвольных длинных задачах. Ни один из этих smoke suites не
доказывает полного равенства качества или всех logits.

## Исторические проверки experimental candidate и ограничения

Следующие passed/skip counts относятся к экспериментальному checkout с
runtime `735ec88`, а не к отдельному релизному checkout нового main.

| Проверка | Результат |
|---|---|
| Первый focused запуск | 87 passed, 4 skipped, 8 failed |
| Повтор focused после исправления окружения и тестового сравнения | **95 passed, 4 skipped**, 10.42 с |
| Более широкий relevant suite | **952 passed, 49 skipped, 4 deselected**, 230.34 с |
| Новый CPU PLE regression на исходном main | **4 expected failures**, 35 deselected, 5.67 с |

Focused и broader suites пересекаются: их passed counts **нельзя складывать**.
Skip и deselected не считаются успешными проверками.

В первом запуске пять failures вызвало отсутствие скопированного native
`_pinned_tensor` extension в candidate. Ещё три были FP32 roundoff порядка
1.07–1.19e-6 при сравнении GEMM с разным числом строк с абсолютным порогом 1e-6.
Тест теперь отдельно требует **точное** восстановление истории из захваченных
conv inputs и сравнивает независимый prefix-only forward с FP32 допуском
`rtol=1e-5, atol=2e-6`. Это не ослабление точного state rollback assertion.

Новые CUDA graph tests прошли на GPU: BF16 state rollback для accepted=1..4,
повторный replay с новыми входами, смена slot 1→3→1, неизменность остальных
слотов и следующий convolution output. Также проверен replay reuse routing.
Это изолированные kernel/layer/graph проверки; они не равнозначны доказательству
совпадения всех logits всей модели. На исходном main CPU regression падает
на отсутствии PLE stash во всех четырёх случаях принятого префикса.

Среди непроверенных путей остаются отдельные HF-reference проверки, требующие
`FREETOKEN_QWEN4_HF_PYTHON`, и checkpoint-reference проверки с отдельным
`needs_weights`/model-path setup. Наличие модели в serving не включает эти
pytest-проверки автоматически. Сохранённые краткие логи не дают полного
разбиения всех 49 skips по причинам; не следует приписывать им GPU-успех.

## Отдельная проверка PLE-only main

| Проверка release suite | Commit | Результат | Время |
|---|---|---|---:|
| Первый запуск нового main | `94bd875` | 14 failed, 167 passed, 48 skipped, 2 deselected | 125.16 с |
| Та же suite на исходном baseline | `9ef483c` | 14 failed, 159 passed, 48 skipped, 2 deselected | 41.20 с |
| Повтор после test-fixture isolation fix | `f56cf78` | **181 passed, 48 skipped, 2 deselected** | 52.82 с |

Во всех 14 failures причиной оказался CPU RoPE cache: тесты
`test_host_embedding` создавали CPU-объекты, которые оставались в
`get_rope` cache и затем попадали в GPU-тесты. FlashInfer сообщал
`cos_sin_cache must be a CUDA tensor`. Те же 14 тестов упали на исходном
`9ef483c`, что воспроизвело проблему изоляции, существовавшую до PLE fix.

Commit `f56cf78` меняет **только fixture** в
`tests/models/qwen4_exp/test_host_embedding.py`: очищает `get_rope` cache
перед и после теста и восстанавливает прежний `_ROPE_DEVICE`. Runtime,
математика модели и tolerances этих 14 проверок не изменены. Повтор завершился
без failures. Эти три запуска пересекаются между собой; их counts нельзя
складывать с историческими 95/952 passed. Skipped/deselected не являются passes,
а различие времени suite не является измерением скорости инференса.

Логи: `logs/ple-only-tests-first.log`, `logs/baseline-suite.log`,
`logs/tests-fixed.log` в локальном evidence этой задачи. Counts, commits и
SHA256 логов записаны отдельно в `selected_release.test_suite_results`
файлов метрик. Исторические benchmark-записи `9ef483c`/`735ec88` не изменены.

Новый источник `/opt/freetoken/src/main-ple-20261001` прошёл warmup и отдельные
serving-проверки. Результаты прежних reuse/lookup проверок не используются
как их замена:

| Собственная проверка PLE-only main | Результат |
|---|---|
| Semantic suite | **9/9 passed**, 54.939 с |
| Retrieval, 240077 input tokens, точные ALPHA/BETA/GAMMA | Pass, 97.465 с |
| Vision, красное изображение 1536×1536 | Pass, 8.501 с |
| `get_weather`, Moscow | Pass, 6.708 с |
| Responses API, READY | Pass, 2.245 с |

Extended API suite прошёл **4/4**. Это ограниченные проверки функций и
регрессий: они не доказывают общее качество модели и не являются отдельным
throughput benchmark новой сборки. Данные и SHA256 первичного evidence:
[selected-release.json](../../benchmarks/rtx5090/data/mtp-20260930/selected-release.json).

Состояние проверено **2026-09-30 22:07:01 UTC** (2026-10-01 01:07:01 MSK):
`freetoken-qwen.service` active/running, `NRestarts=0`, enabled. Постоянный
source override указывает на новый checkout; временный test override отсутствует.
Python path и runtime соответствуют проверенному `f56cf78`, launcher не изменён.
Health и warmup содержат один instance ID:
`4f9cc8f8-8852-4eed-9bd6-2ec0df6deb0b`; warmup status `warm`, health `ok`.

`FT_SPEC_LOOKUP`, `FREETOKEN_HYBRID_FETCH_REUSE` и `FT_SPEC_PLE_ROLLBACK`
не заданы. Для PLE это означает **исправление включено по умолчанию**, а не
отключено. Lookup/reuse runtime-кода в этой сборке нет.

## Как повторить throughput-запросы

Команды ниже выполняются **после** контролируемого запуска и warmup нужного
исторического профиля из таблицы, при отсутствии другой нагрузки. Для
lookup/reuse/both нужен experimental candidate `735ec88`; новый main этих
реализаций не содержит. Команды сами не переключают
сервис: переменные окружения клиентского процесса не меняют уже работающий
server. Каталог результата выбран отдельно от исходного evidence.

```bash
cd /opt/freetoken/src/mtp-lab-20260930
profile=reuse
for temp in 0 1; do
  /opt/freetoken/venv/bin/python benchmarks/rtx5090/stream_bench.py \
    --base http://127.0.0.1:1919 \
    --model qwen38-flash-next \
    --label "${profile}-t${temp}" \
    --output "/srv/freetoken/perf/mtp-validation-reproduction/${profile}" \
    --tokens 512 --repeats 2 --temperature "$temp" --lengths 0 \
    --thinking medium --seed "screen-t${temp}" \
    --prompt-file benchmarks/rtx5090/fixtures/real-code-prompt.txt.gz
done
```

`--lengths 0` отключает синтетический padding: вход берётся из fixture и по
server usage составляет 104869 токенов. `--seed` здесь фиксирует **nonce в
prompt**, а не RNG семплера. Repeat nonce отличается между двумя повторами,
но совпадает у соответствующих повторов разных профилей. Поэтому одинаковая
температура и эта опция не гарантируют идентичный ответ, включая T0.

Для завершённых confirmation-нагрузок использовались следующие аргументы
того же клиента: первая команда на base/reuse, вторая на base/reuse/lookup.

```bash
/opt/freetoken/venv/bin/python benchmarks/rtx5090/stream_bench.py \
  --label "${profile}-t1" \
  --output "/srv/freetoken/perf/mtp-validation-reproduction/confirm/${profile}" \
  --tokens 1024 --repeats 3 --temperature 1 --lengths 0 \
  --thinking medium --seed confirm-t1 \
  --prompt-file benchmarks/rtx5090/fixtures/real-code-prompt.txt.gz

/opt/freetoken/venv/bin/python benchmarks/rtx5090/stream_bench.py \
  --label "${profile}-edit" \
  --output "/srv/freetoken/perf/mtp-validation-reproduction/confirm/${profile}" \
  --tokens 1024 --repeats 2 --temperature 0 --lengths 0 \
  --thinking off --seed confirm-edit \
  --prompt-file benchmarks/rtx5090/fixtures/mtp-edit-prompt.txt
```

Source-edit [fixture](../../benchmarks/rtx5090/fixtures/mtp-edit-prompt.txt) и
[metadata](../../benchmarks/rtx5090/fixtures/mtp-edit-prompt.metadata.json)
фиксируют исходный файл, его SHA256, ожидаемую правку и SHA256 полного
ожидаемого результата; модель выдала только ограниченный префикс этого результата.

## Решение: PLE fix принимается, скоростные прототипы остаются отдельно

Существенное устойчивое ускорение экспериментальных профилей не подтверждено.
**Полная experimental ветка не сливается в main; lookup/reuse runtime-код и
его флаги в новый main не включены.** Если эти прототипы используются в
экспериментальной ветке, рекомендация для текущей конфигурации - default off.

В main отдельно перенесено исправление PLE convolution history с CPU/CUDA
graph регрессионными тестами: runtime commit `7d296eced5bd3f388ebf325c3300172383318b34`.
Semantic harness и source-edit fixture добавлены в commit
`94bd875ed2622df2e3b78948a5c8a502c47985de`; commit
`f56cf78cefbb931079f114de5368e2596034ab3b` изолирует тестовый CPU RoPE cache.
Модель, NVFP4, BF16 KV,
контекст 262144 и MTP3 сохраняются. Это выбор полезного исправления
корректности, а не заявление о подтверждённом ускорении нового main.

**PLE-only status: tests, serving validation и deployment подтверждены.**
Выбранный новый checkout прошёл собственные 181 тест, 9 semantic и 4 API checks;
готовность сервиса и health/warmup instance IDs зафиксированы выше.
Исторические 95/952 passed, 27 semantic и 4 API checks experimental candidate
не переатрибутируются новому main.

Проверенный source commit - `f56cf78cefbb931079f114de5368e2596034ab3b`.
Итоговый main может дополнительно содержать документационный commit с этим
отчётом и evidence: если runtime-файлы не меняются, это документирование той
же проверенной сборки, а не новый замер. Публикация `f56cf78` в GitHub main
подтверждена; серверный checkout также сопоставлен с удалённой веткой.

## Evidence и последующая актуализация

- [Числа всех 20 прогонов и SHA256](../../benchmarks/rtx5090/data/mtp-20260930/screen-metrics.json):
  usage, тайминги, output SHA256 и SHA256 исходных JSON; без output text,
  previews, SSE delta и credentials.
- [Confirmation: 12 throughput-прогонов, 27 semantic и 4 API checks](../../benchmarks/rtx5090/data/mtp-20260930/confirm-metrics.json):
  только метрики, результаты проверок и хеши; raw responses и payloads исключены.
- [Выбранный PLE-only release](../../benchmarks/rtx5090/data/mtp-20260930/selected-release.json):
  собственные test/semantic/API результаты, deployment и хеши исходных логов.
- Полный локальный evidence: `outputs/freetoken-mtp-validation-20260930/`
  в workspace задачи; `screen/`, `confirm-base/`, `reuse/`, `lookup/`, `logs/`,
  `ple-only/`, `WORKLOG.md`, `edit-checks-confirm.json`. Локальные `reuse/` и `lookup/`
  скопированы из удалённых `confirm/reuse/` и `confirm/lookup/`. На сервере:
  `/srv/freetoken/perf/mtp-validation-20260930`.
- Предшествующий инженерный разбор `THROUGHPUT_REVIEW_20260930.md` сохранён в
  локальной экспериментальной ветке `exp/qwen38-throughput-reviewed-20260930`.
  В выбранный main он не переносится вместе с lookup/reuse прототипами.
  Для фактических результатов эксперимента используются настоящий отчёт и
  исторические commit SHA в метриках.

**Решение о составе нового main: принять PLE correctness fix, не переносить
lookup/reuse.** Его собственная проверка и запуск завершены; скорость новой
PLE-only сборки не подменяется историческими замерами других профилей.
