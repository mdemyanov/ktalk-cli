import json


class TestHelpers:
    def test_format_duration_minutes_only(self):
        from ktalk_cli.formatters import _format_duration

        assert _format_duration(300) == "5 мин"
        assert _format_duration(45) == "1 мин"
        assert _format_duration(0) == "0 мин"

    def test_format_duration_hours_and_minutes(self):
        from ktalk_cli.formatters import _format_duration

        assert _format_duration(3600) == "1 ч 0 мин"
        assert _format_duration(4800) == "1 ч 20 мин"
        assert _format_duration(7260) == "2 ч 1 мин"

    def test_format_duration_none_returns_dash(self):
        """ADR-026 §3 (находка issue #13, замер): значение отсутствует (`None`) —
        не тот же исход, что «0 секунд» (уже покрыт `test_format_duration_minutes_only`).
        Красный сегодня: `_format_duration` принимает только `int`, `None < 3600`
        поднимает `TypeError`, не возвращает `"—"`."""
        from ktalk_cli.formatters import _format_duration

        assert _format_duration(None) == "—"


class TestDurationNoneVsZero:
    """ADR-026 §3: два РАЗНЫХ исхода — разные фикстуры, не одна с ветвлением
    внутри теста (companion-спека, «Edge cases»)."""

    def test_format_recording_without_duration_key_shows_dash_not_zero_minutes(self):
        from ktalk_cli.formatters import format_recording

        data = {
            "key": "rec-no-duration",
            "title": "Без длительности в ответе контура",
            "createdDate": "2026-04-01T10:00:00Z",
            "createdBy": {"surname": "Иванов", "firstname": "Иван"},
            # намеренно без ключа "duration" — реальная форма ответа внутреннего контура
        }

        result = format_recording(data)
        assert "—" in result
        assert "0 мин" not in result

    def test_format_recording_with_duration_zero_still_shows_zero_minutes(self):
        """Регрессия: явный `duration: 0` — валидный факт («встреча длилась 0 секунд»),
        не путается с отсутствием значения."""
        from ktalk_cli.formatters import format_recording

        data = {
            "key": "rec-zero-duration",
            "title": "Явный ноль",
            "createdDate": "2026-04-01T10:00:00Z",
            "createdBy": {"surname": "Иванов", "firstname": "Иван"},
            "duration": 0,
        }

        result = format_recording(data)
        assert "0 мин" in result

    def test_format_recordings_list_without_duration_key_shows_dash_not_zero_minutes(self):
        from ktalk_cli.formatters import format_recordings_list

        data = {
            "recordings": [
                {
                    "id": "rec-no-duration",
                    "title": "Без длительности",
                    "createdDate": "2026-04-01T10:00:00Z",
                    "createdBy": {"surname": "Иванов", "firstname": "Иван"},
                    "roomName": "standup",
                    # без ключа "duration"
                }
            ],
            "nextPageToken": None,
            "prevPageToken": None,
        }

        result = format_recordings_list(data)
        assert "—" in result
        assert "0 мин" not in result

    def test_format_timestamp_millis(self):
        from ktalk_cli.formatters import _format_timestamp

        assert _format_timestamp(0) == "00:00:00"
        assert _format_timestamp(15000) == "00:00:15"
        assert _format_timestamp(102000) == "00:01:42"
        assert _format_timestamp(3723000) == "01:02:03"

    def test_format_user_name_full(self):
        from ktalk_cli.formatters import _format_user_name

        user_ref = {
            "userInfo": {"surname": "Иванов", "firstname": "Иван", "login": "iivanov"},
            "isAnonymous": False,
        }
        assert _format_user_name(user_ref) == "Иванов Иван"

    def test_format_user_name_login_fallback(self):
        from ktalk_cli.formatters import _format_user_name

        user_ref = {
            "userInfo": {"surname": None, "firstname": None, "login": "iivanov"},
            "isAnonymous": False,
        }
        assert _format_user_name(user_ref) == "iivanov"

    def test_format_user_name_anonymous(self):
        from ktalk_cli.formatters import _format_user_name

        user_ref = {
            "anonymousName": "Гость 1",
            "userInfo": None,
            "isAnonymous": True,
        }
        assert _format_user_name(user_ref) == "Гость 1"

    def test_format_user_name_no_info(self):
        from ktalk_cli.formatters import _format_user_name

        assert _format_user_name(None) == "Неизвестный"
        assert _format_user_name({}) == "Неизвестный"

    def test_format_user_name_from_talk_user(self):
        from ktalk_cli.formatters import _format_user_name_from_user

        user = {"surname": "Петрова", "firstname": "Мария", "login": "mpetrova"}
        assert _format_user_name_from_user(user) == "Петрова Мария"

    def test_format_user_name_from_talk_user_short(self):
        from ktalk_cli.formatters import _format_user_name_short

        user = {"surname": "Иванов", "firstname": "Иван"}
        assert _format_user_name_short(user) == "Иванов И."

    def test_format_datetime(self):
        from ktalk_cli.formatters import _format_datetime

        assert _format_datetime("2026-04-01T10:00:00Z") == "2026-04-01 10:00"
        assert _format_datetime("2026-04-01T10:30:45.123Z") == "2026-04-01 10:30"
        assert _format_datetime(None) == ""

    def test_format_raw(self):
        from ktalk_cli.formatters import format_raw

        data = {"key": "value", "число": 42}
        result = format_raw(data)
        parsed = json.loads(result)
        assert parsed == data
        assert "число" in result  # ensure_ascii=False


class TestFormatRecordingsList:
    def test_basic_list(self):
        from ktalk_cli.formatters import format_recordings_list

        data = {
            "recordings": [
                {
                    "id": "rec-001",
                    "title": "Стендап команды",
                    "createdDate": "2026-04-01T10:00:00Z",
                    "createdBy": {
                        "surname": "Иванов",
                        "firstname": "Иван",
                        "login": "iivanov",
                        "key": "101",
                    },
                    "duration": 2700,
                    "participantsCount": 2,
                    "participants": [
                        {
                            "userInfo": {
                                "surname": "Иванов",
                                "firstname": "Иван",
                                "key": "201",
                            },
                            "isAnonymous": False,
                        },
                        {
                            "userInfo": {
                                "surname": "Петрова",
                                "firstname": "Мария",
                                "key": "202",
                            },
                            "isAnonymous": False,
                        },
                    ],
                    "roomName": "standup",
                },
                {
                    "id": "rec-002",
                    "title": "Ретро спринта",
                    "createdDate": "2026-03-28T14:00:00Z",
                    "createdBy": {
                        "surname": "Петрова",
                        "firstname": "Мария",
                        "login": "mpetrova",
                        "key": "102",
                    },
                    "duration": 4800,
                    "participantsCount": 1,
                    "participants": [
                        {
                            "userInfo": {
                                "surname": "Петрова",
                                "firstname": "Мария",
                                "key": "202",
                            },
                            "isAnonymous": False,
                        },
                    ],
                    "roomName": "retro",
                },
            ],
            "nextPageToken": "abc123",
            "prevPageToken": None,
        }

        result = format_recordings_list(data)
        assert "# Записи KTalk" in result
        assert "rec-001" in result
        assert "rec-002" in result
        assert "Стендап команды" in result
        assert "Ретро спринта" in result
        assert "Иванов Иван (101)" in result
        assert "Петрова Мария (102)" in result
        assert "Иванов Иван (201), Петрова Мария (202)" in result
        assert "45 мин" in result
        assert "1 ч 20 мин" in result
        assert "abc123" in result

    def test_empty_list(self):
        from ktalk_cli.formatters import format_recordings_list

        data = {"entities": [], "nextPageToken": None, "prevPageToken": None}
        result = format_recordings_list(data)
        assert "Записей не найдено" in result

    def test_no_next_page(self):
        from ktalk_cli.formatters import format_recordings_list

        data = {
            "entities": [
                {
                    "key": "rec-001",
                    "title": "Test",
                    "createdDate": "2026-04-01T10:00:00Z",
                    "createdBy": {"surname": "Test", "firstname": "User"},
                    "duration": 600,
                    "participantsCount": 2,
                    "roomName": "test",
                },
            ],
            "nextPageToken": None,
            "prevPageToken": None,
        }
        result = format_recordings_list(data)
        assert "page_token" not in result


class TestFormatRecording:
    def test_full_recording(self):
        from ktalk_cli.formatters import format_recording

        data = {
            "key": "rec-abc-123",
            "title": "Стендап команды",
            "createdDate": "2026-04-01T10:00:00Z",
            "createdBy": {
                "surname": "Иванов",
                "firstname": "Иван",
                "login": "iivanov",
            },
            "roomName": "standup-room",
            "duration": 2700,
            "participantsCount": 3,
            "participants": [
                {
                    "userInfo": {"surname": "Иванов", "firstname": "Иван"},
                    "isAnonymous": False,
                },
                {
                    "userInfo": {"surname": "Петрова", "firstname": "Мария"},
                    "isAnonymous": False,
                },
                {
                    "anonymousName": "Гость",
                    "userInfo": None,
                    "isAnonymous": True,
                },
            ],
        }

        result = format_recording(data)
        assert "# Стендап команды" in result
        assert "rec-abc-123" in result
        assert "2026-04-01 10:00" in result
        assert "Иванов Иван" in result
        assert "standup-room" in result
        assert "45 мин" in result
        assert "Петрова Мария" in result
        assert "Гость" in result

    def test_recording_no_participants(self):
        from ktalk_cli.formatters import format_recording

        data = {
            "key": "rec-001",
            "title": "Solo",
            "createdDate": "2026-04-01T10:00:00Z",
            "createdBy": {"surname": "Test", "firstname": "User"},
            "duration": 60,
            "participantsCount": 0,
            "participants": [],
        }

        result = format_recording(data)
        assert "# Solo" in result


class TestFormatTranscript:
    def test_complete_transcript(self):
        from ktalk_cli.formatters import format_transcript

        data = {
            "status": "complete",
            "tracks": [
                {
                    "trackId": "track-1",
                    "speaker": {
                        "userInfo": {
                            "surname": "Иванов",
                            "firstname": "Иван",
                            "login": "iivanov",
                        },
                        "isAnonymous": False,
                    },
                    "chunks": [
                        {
                            "chunkId": "c1",
                            "startTimeOffsetInMillis": 15000,
                            "endTimeOffsetInMillis": 30000,
                            "text": "Доброе утро, давайте начнём.",
                        },
                    ],
                },
                {
                    "trackId": "track-2",
                    "speaker": {
                        "userInfo": {
                            "surname": "Петрова",
                            "firstname": "Мария",
                            "login": "mpetrova",
                        },
                        "isAnonymous": False,
                    },
                    "chunks": [
                        {
                            "chunkId": "c2",
                            "startTimeOffsetInMillis": 102000,
                            "endTimeOffsetInMillis": 120000,
                            "text": "У меня вчера было две задачи.",
                        },
                    ],
                },
            ],
        }

        result = format_transcript(data)
        assert "# Транскрипт" in result
        assert "**Иванов Иван** [00:00:15]" in result
        assert "Доброе утро, давайте начнём." in result
        assert "**Петрова Мария** [00:01:42]" in result
        assert "У меня вчера было две задачи." in result

    def test_transcript_in_progress(self):
        from ktalk_cli.formatters import format_transcript

        data = {"status": "inProgress", "tracks": None}
        result = format_transcript(data)
        assert "В обработке" in result

    def test_transcript_error(self):
        from ktalk_cli.formatters import format_transcript

        data = {"status": "error", "statusMessage": "Failed to process", "tracks": None}
        result = format_transcript(data)
        assert "Ошибка" in result

    def test_transcript_multiple_chunks_per_track(self):
        from ktalk_cli.formatters import format_transcript

        data = {
            "status": "complete",
            "tracks": [
                {
                    "trackId": "track-1",
                    "speaker": {
                        "userInfo": {"surname": "Иванов", "firstname": "Иван"},
                        "isAnonymous": False,
                    },
                    "chunks": [
                        {
                            "chunkId": "c1",
                            "startTimeOffsetInMillis": 1000,
                            "text": "Первая фраза.",
                        },
                        {
                            "chunkId": "c2",
                            "startTimeOffsetInMillis": 5000,
                            "text": "Вторая фраза.",
                        },
                    ],
                },
            ],
        }

        result = format_transcript(data)
        assert "Первая фраза." in result
        assert "Вторая фраза." in result


class TestFormatSummary:
    def test_composite_summary(self):
        from ktalk_cli.formatters import format_summary

        data = {
            "shortSummaryV2": {
                "status": "success",
                "chunks": [
                    {"type": "text", "text": "Обсудили планы на спринт.", "timestamp": 0},
                    {"type": "text", "text": "Распределили задачи.", "timestamp": 60000},
                ],
            },
            "protocolV2": {
                "status": "success",
                "chunks": [
                    {"type": "heading", "text": "Решения", "timestamp": 0},
                    {"type": "text", "text": "1. Запустить MVP до пятницы.", "timestamp": 30000},
                ],
            },
            "transcriptionV2": {
                "status": "success",
                "tracks": [],
            },
        }

        result = format_summary(data)
        assert "## Краткое резюме" in result
        assert "Обсудили планы на спринт." in result
        assert "Распределили задачи." in result
        assert "## Протокол" in result
        assert "Решения" in result
        assert "Запустить MVP до пятницы." in result

    def test_summary_in_progress(self):
        from ktalk_cli.formatters import format_summary

        data = {
            "shortSummaryV2": {"status": "inProgress", "chunks": None},
            "protocolV2": {"status": "inProgress", "chunks": None},
            "transcriptionV2": {"status": "success", "tracks": []},
        }

        result = format_summary(data)
        assert "В обработке" in result

    def test_summary_partial(self):
        from ktalk_cli.formatters import format_summary

        data = {
            "shortSummaryV2": {
                "status": "success",
                "chunks": [{"type": "text", "text": "Краткое.", "timestamp": 0}],
            },
            "protocolV2": {"status": "failed", "chunks": None},
            "transcriptionV2": {"status": "success", "tracks": []},
        }

        result = format_summary(data)
        assert "Краткое." in result
        assert "недоступен" in result.lower() or "ошибка" in result.lower()


class TestFormatSummaryByType:
    def test_short_summary(self):
        from ktalk_cli.formatters import format_summary_by_type

        data = {
            "status": "success",
            "chunks": [
                {"type": "text", "text": "Обсуждение задач спринта.", "timestamp": 0},
                {"type": "text", "text": "Все согласны с планом.", "timestamp": 120000},
            ],
        }

        result = format_summary_by_type(data, "shortSummary")
        assert "Краткое резюме" in result
        assert "Обсуждение задач спринта." in result
        assert "Все согласны с планом." in result

    def test_protocol(self):
        from ktalk_cli.formatters import format_summary_by_type

        data = {
            "status": "success",
            "chunks": [
                {"type": "heading", "text": "Решения", "timestamp": 0},
                {"type": "text", "text": "Запустить MVP.", "timestamp": 30000},
            ],
        }

        result = format_summary_by_type(data, "protocol")
        assert "Протокол" in result
        assert "Решения" in result
        assert "Запустить MVP." in result

    def test_summary_not_found(self):
        from ktalk_cli.formatters import format_summary_by_type

        data = {"status": "notFound", "chunks": None}
        result = format_summary_by_type(data, "shortSummary")
        assert "не найден" in result.lower() or "недоступ" in result.lower()


class TestChunkTranscriptMarkdown:
    def test_small_text_single_chunk(self):
        from ktalk_cli.formatters import chunk_transcript_markdown

        text = "# Транскрипт\n\n**Иванов Иван** [00:00:15]: Короткая фраза."
        result = chunk_transcript_markdown(text, chunk_size=5000)
        assert result == [text]

    def test_splits_at_utterance_boundary(self):
        from ktalk_cli.formatters import chunk_transcript_markdown

        # Build transcript with 3 utterances, ~50 chars each
        utterances = [
            "**Иванов Иван** [00:00:15]: Первая реплика тестовая.",
            "**Петрова Мария** [00:01:00]: Вторая реплика тестовая.",
            "**Иванов Иван** [00:02:00]: Третья реплика тестовая.",
        ]
        text = "# Транскрипт\n\n" + "\n\n".join(utterances)

        # chunk_size enough for header + 2 utterances but not 3
        header_len = len("# Транскрипт\n\n")
        two_utterances_len = len(utterances[0]) + 2 + len(utterances[1])
        chunk_size = header_len + two_utterances_len + 10  # small margin

        result = chunk_transcript_markdown(text, chunk_size=chunk_size)
        assert len(result) == 2
        assert result[0].startswith("# Транскрипт\n\n")
        assert result[1].startswith("# Транскрипт\n\n")
        assert "Первая реплика" in result[0]
        assert "Вторая реплика" in result[0]
        assert "Третья реплика" in result[1]

    def test_single_long_utterance_not_split(self):
        from ktalk_cli.formatters import chunk_transcript_markdown

        long_text = "A" * 10000
        text = f"# Транскрипт\n\n**Иванов Иван** [00:00:00]: {long_text}"
        result = chunk_transcript_markdown(text, chunk_size=100)
        # Single utterance should never be split even if > chunk_size
        assert len(result) == 1
        assert long_text in result[0]

    def test_empty_transcript(self):
        from ktalk_cli.formatters import chunk_transcript_markdown

        text = "# Транскрипт\n\nТранскрипт пуст."
        result = chunk_transcript_markdown(text, chunk_size=5000)
        assert result == [text]

    def test_error_status_not_split(self):
        from ktalk_cli.formatters import chunk_transcript_markdown

        text = "# Транскрипт\n\nОшибка транскрипции: failed"
        result = chunk_transcript_markdown(text, chunk_size=5000)
        assert result == [text]


class TestChunkTranscriptRaw:
    def _make_transcript_data(self, num_chunks_per_track=1, num_tracks=2):
        """Helper to build transcript API data with given number of entries."""
        tracks = []
        time_offset = 0
        for t in range(num_tracks):
            chunks = []
            for c in range(num_chunks_per_track):
                chunks.append({
                    "chunkId": f"c-{t}-{c}",
                    "startTimeOffsetInMillis": time_offset,
                    "endTimeOffsetInMillis": time_offset + 15000,
                    "text": f"Реплика {t}-{c} " + "x" * 50,
                })
                time_offset += 15000
            tracks.append({
                "trackId": f"track-{t}",
                "speaker": {
                    "userInfo": {"surname": f"Speaker{t}", "firstname": f"Name{t}"},
                    "isAnonymous": False,
                },
                "chunks": chunks,
            })
        return {"status": "complete", "tracks": tracks}

    def test_small_data_single_chunk(self):
        from ktalk_cli.formatters import chunk_transcript_raw

        data = self._make_transcript_data(num_chunks_per_track=1, num_tracks=2)
        result = chunk_transcript_raw(data, chunk_size=50000)
        assert len(result) == 1
        parsed = json.loads(result[0])
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    def test_splits_into_multiple_chunks(self):
        from ktalk_cli.formatters import chunk_transcript_raw

        data = self._make_transcript_data(num_chunks_per_track=5, num_tracks=2)
        # 10 entries total, each ~100+ chars serialized, use small chunk_size
        result = chunk_transcript_raw(data, chunk_size=500)
        assert len(result) > 1
        # All entries present across chunks
        all_entries = []
        for chunk_str in result:
            all_entries.extend(json.loads(chunk_str))
        assert len(all_entries) == 10

    def test_entries_sorted_by_time(self):
        from ktalk_cli.formatters import chunk_transcript_raw

        data = self._make_transcript_data(num_chunks_per_track=3, num_tracks=2)
        result = chunk_transcript_raw(data, chunk_size=50000)
        entries = json.loads(result[0])
        timestamps = [e["timestamp_ms"] for e in entries]
        assert timestamps == sorted(timestamps)

    def test_empty_tracks(self):
        from ktalk_cli.formatters import chunk_transcript_raw

        data = {"status": "complete", "tracks": []}
        result = chunk_transcript_raw(data, chunk_size=5000)
        assert len(result) == 1
        assert json.loads(result[0]) == []


class TestTranscriptChunkingIntegration:
    """Test the complete chunking flow: format → chunk → metadata."""

    def _make_long_transcript_data(self, num_entries: int) -> dict:
        """Build transcript data that produces a large markdown output."""
        tracks = [{
            "trackId": "track-0",
            "speaker": {
                "userInfo": {"surname": "Тестов", "firstname": "Тест"},
                "isAnonymous": False,
            },
            "chunks": [
                {
                    "chunkId": f"c{i}",
                    "startTimeOffsetInMillis": i * 15000,
                    "text": f"Реплика номер {i}. " + "Текст " * 20,
                }
                for i in range(num_entries)
            ],
        }]
        return {"status": "complete", "tracks": tracks}

    def test_chunk0_small_returns_plain_string(self):
        """chunk=0 + small transcript -> plain string (backward compat)."""
        from ktalk_cli.formatters import chunk_transcript_markdown, format_transcript

        data = self._make_long_transcript_data(3)
        text = format_transcript(data)
        chunks = chunk_transcript_markdown(text, chunk_size=50000)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunk0_large_returns_first_chunk(self):
        """chunk=0 + large transcript -> auto-chunks, returns first."""
        from ktalk_cli.formatters import chunk_transcript_markdown, format_transcript

        data = self._make_long_transcript_data(50)
        text = format_transcript(data)
        assert len(text) > 1000
        chunks = chunk_transcript_markdown(text, chunk_size=1000)
        assert len(chunks) > 1

    def test_chunk_metadata_structure(self):
        """Verify metadata JSON structure."""
        from ktalk_cli.formatters import chunk_transcript_markdown, format_transcript

        data = self._make_long_transcript_data(50)
        text = format_transcript(data)
        chunks = chunk_transcript_markdown(text, chunk_size=1000)
        total = len(chunks)

        # Simulate what the tool would return for chunk=2
        metadata = {
            "result": chunks[1],
            "chunk": 2,
            "total_chunks": total,
            "has_more": 2 < total,
            "total_characters": len(text),
        }
        result = json.dumps(metadata, ensure_ascii=False, indent=2)
        parsed = json.loads(result)
        assert parsed["chunk"] == 2
        assert parsed["total_chunks"] == total
        assert parsed["has_more"] is True
        assert parsed["total_characters"] == len(text)
        assert "# Транскрипт" in parsed["result"]
