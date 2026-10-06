"""A provider's fallback/chart result cannot become another song's guide."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from lyrics_search import lyrics_match_score, relevant_lyrics_results, select_automatic_lyrics
from lyric_drafts import read_draft, write_draft, draft_path
from test_automatic_lyrics_and_search import load_function, HTTPError

NOKIA = dict(track_name='NOKIA', artist_name='Drake', has_lyrics=True, lyrics_text='Unrelated guide', provider='Musixmatch')
SONG = dict(track_name='Tracing A Dream', artist_name='YOASOBI', has_lyrics=True, lyrics_text='Correct guide', provider='LRCLIB')
VIDEO_TITLE = 'YOASOBI / Tracing A Dream (あの夢をなぞって English Ver.)'


class LyricsIdentityTests(unittest.TestCase):
    def test_unrelated_nokia_is_rejected_by_both_search_modes_and_pipeline(self):
        for query in (VIDEO_TITLE, 'Tracing A Dream', 'YOASOBI', 'YOASOBI - Tracing A Dream', 'Artista - Canção'):
            for automatic in (False, True):
                self.assertEqual(lyrics_match_score(query, NOKIA, automatic), 0)
            self.assertEqual(relevant_lyrics_results(query, [NOKIA]), [])
            self.assertIsNone(select_automatic_lyrics(query, [NOKIA]))
            lookup = load_function('find_lyrics_automatically', search_lyrics_providers=lambda _: [NOKIA])
            self.assertEqual(lookup(query), ('', None))

    def test_manual_title_artist_partial_and_typo_queries_remain_available(self):
        for query in ('YOASOBI', 'Tracing A Dream', 'Tracing', 'Tracin A Dream', 'Tracing A Dream YOASOBI'):
            self.assertEqual(relevant_lyrics_results(query, [NOKIA, SONG]), [SONG])

    def test_automatic_requires_artist_and_title_and_supports_title_order(self):
        for query in ('YOASOBI - Tracing A Dream', 'YOASOBI / Tracing A Dream', 'Tracing A Dream — YOASOBI', 'YOASOBI Tracing A Dream Official Video'):
            self.assertEqual(select_automatic_lyrics(query, [NOKIA, SONG]), SONG)
        for query in ('Tracing A Dream', 'Different artist - Tracing A Dream', 'YOASOBI - Different song'):
            self.assertIsNone(select_automatic_lyrics(query, [SONG]))
        for query in ('YOASOBI - Another Tracing A Dream', 'YOASOBI - Tracing A Dream (Part 2)'):
            self.assertIsNone(select_automatic_lyrics(query, [SONG]))

    def test_language_and_performance_variants_require_manual_confirmation(self):
        self.assertIsNone(select_automatic_lyrics(VIDEO_TITLE, [SONG]))
        english = {**SONG, 'track_name':'Tracing A Dream (English Version)'}
        self.assertEqual(select_automatic_lyrics(VIDEO_TITLE, [english]), english)
        self.assertEqual(relevant_lyrics_results(VIDEO_TITLE, [NOKIA, english]), [english])
        for version in ('live', 'remix', 'cover', 'slowed'):
            self.assertIsNone(select_automatic_lyrics('YOASOBI - Tracing A Dream '+version, [SONG]))

    def test_unicode_and_punctuation_are_kept_for_identity(self):
        japanese = {**SONG, 'track_name':'あの夢をなぞって'}
        self.assertEqual(select_automatic_lyrics('YOASOBI / あの夢をなぞって', [japanese]), japanese)
        portuguese = {**SONG, 'track_name':'Canção', 'artist_name':'Artísta'}
        self.assertEqual(select_automatic_lyrics('Artista - Cancao (Official Video).mp4', [portuguese]), portuguese)
        slash_artist = {**SONG, 'track_name':'Thunderstruck', 'artist_name':'AC/DC'}
        self.assertEqual(select_automatic_lyrics('AC/DC - Thunderstruck', [slash_artist]), slash_artist)

    def test_matching_instrumental_or_empty_provider_data_does_not_import(self):
        for record in ({**SONG, 'instrumental':True}, {**SONG, 'has_lyrics':False}, {**SONG, 'lyrics_text':''}):
            self.assertIsNone(select_automatic_lyrics('YOASOBI - Tracing A Dream', [record]))

    def test_lrc_text_wins_without_using_external_word_clocks(self):
        synced = {**SONG, 'lyrics_text':'', 'synced_lyrics':'[00:01]Correct guide'}
        selected = select_automatic_lyrics('YOASOBI - Tracing A Dream', [SONG, synced])
        self.assertEqual(selected['lyrics_text'], 'Correct guide')
        self.assertEqual(selected['synced_lyrics'], synced['synced_lyrics'])


class LyricsProviderTests(unittest.TestCase):
    def musixmatch(self, record):
        body = {'macro_calls': {
            'matcher.track.get': {'message':{'body':{'track':record}}},
            'track.lyrics.get': {'message':{'body':{'lyrics':{'lyrics_body':'Guide'}}}},
        }}
        return load_function('_musixmatch_record', _musixmatch_token=lambda:'token',
            _lyrics_provider_get=Mock(return_value={'message':{'body':body}}),
            MUSIXMATCH_API_URL='https://provider.test', MUSIXMATCH_APP_ID='app', json=json)

    def test_musixmatch_default_chart_response_is_discarded_at_provider_boundary(self):
        fetch = self.musixmatch({'track_name':'NOKIA','artist_name':'Drake'})
        self.assertIsNone(fetch('YOASOBI', 'Tracing A Dream'))
        self.assertIsNone(fetch('', VIDEO_TITLE))
        self.assertIsNone(fetch('', 'Tracing A Dream'))

    def test_musixmatch_cannot_invent_identity_when_provider_omits_it(self):
        self.assertIsNone(self.musixmatch({})('YOASOBI', 'Tracing A Dream'))

    def test_matching_musixmatch_response_remains_available(self):
        fetch = self.musixmatch({'track_name':'Tracing A Dream','artist_name':'YOASOBI'})
        self.assertEqual(fetch('YOASOBI', 'Tracing A Dream')['lyrics_text'], 'Guide')

    def test_manual_api_omits_unrelated_results_and_lyrics_bodies(self):
        search = load_function('search_lyrics_online', LyricsSearchRequest=object, search_lyrics_providers=lambda _: [NOKIA, SONG])
        result = search(SimpleNamespace(query='Tracing A Dream', automatic=False), {})
        self.assertEqual(len(result['results']), 1)
        self.assertEqual(result['results'][0]['artist_name'], 'YOASOBI')
        self.assertNotIn('lyrics_text', result['results'][0])
        self.assertNotIn('automatic_match', result)

    def test_automatic_api_returns_only_confirmed_guide(self):
        search = load_function('search_lyrics_online', LyricsSearchRequest=object, search_lyrics_providers=lambda _: [NOKIA, SONG])
        result = search(SimpleNamespace(query='YOASOBI / Tracing A Dream', automatic=True), {})
        self.assertEqual(result['automatic_match']['lyrics_text'], 'Correct guide')
        missing = search(SimpleNamespace(query=VIDEO_TITLE, automatic=True), {})
        self.assertIsNone(missing['automatic_match'])

    def test_api_empty_match_is_not_a_provider_or_http_failure(self):
        search = load_function('search_lyrics_online', LyricsSearchRequest=object, search_lyrics_providers=lambda _: [NOKIA])
        result = search(SimpleNamespace(query=VIDEO_TITLE, automatic=True), {})
        self.assertEqual(result['results'], [])
        self.assertIsNone(result['automatic_match'])
        self.assertIn('Whisper', result['message'])

    def test_invalid_query_does_not_call_any_provider(self):
        providers = Mock()
        search = load_function('search_lyrics_online', LyricsSearchRequest=object, search_lyrics_providers=providers)
        for query in (' ', 'a', 'x'*161):
            with self.assertRaises(HTTPError): search(SimpleNamespace(query=query, automatic=True), {})
        providers.assert_not_called()

    def test_new_draft_inherits_default_but_explicit_manual_choice_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(read_draft(folder, 'new')['has_draft'])
            write_draft(folder, 'new', '', 'manual')
            self.assertTrue(read_draft(folder, 'new')['has_draft'])
            self.assertEqual(read_draft(folder, 'new')['lyrics_mode'], 'manual')

    def test_old_automatic_drafts_are_rechecked_but_manual_drafts_remain(self):
        with tempfile.TemporaryDirectory() as folder:
            for mode in ('auto', 'manual'):
                write_draft(folder, mode, 'NOKIA', mode)
                Path(draft_path(folder, mode)).write_text(json.dumps({'lyrics_text':'NOKIA', 'lyrics_mode':mode}))
            self.assertEqual(read_draft(folder, 'auto')['lyrics_text'], '')
            self.assertEqual(read_draft(folder, 'manual')['lyrics_text'], 'NOKIA')
            write_draft(folder, 'auto', 'Verified guide', 'auto')
            self.assertEqual(read_draft(folder, 'auto')['lyrics_text'], 'Verified guide')


if __name__ == '__main__':
    unittest.main()
