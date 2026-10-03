"""Lyrics may guide spelling, but only local recognition can supply word clocks."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from lyric_guide import prepare_lyrics_guide, verify_lyrics_guide, review_lyrics_with_whisper
from karaoke_generator import split_and_wrap_segments, generate_ass_karaoke


def acoustic(text, start=4, probability=None):
    words = [dict(word=' '+word, start=start+i*.4, end=start+i*.4+.3)
             for i, word in enumerate(text.split())]
    if probability is not None:
        for word in words:
            word['probability'] = probability
    return [dict(start=words[0]['start'], end=words[-1]['end'], text=text, words=words)]


def clocks(segments):
    return [(w['start'], w['end']) for s in segments for w in s['words']]


class LyricGuideTests(unittest.TestCase):
    def test_all_words_are_checked_and_spelling_is_corrected_without_mutation(self):
        voice = acoustic('eu quero gastar com voce nesta noite')
        before = copy.deepcopy(voice)
        checked, report = verify_lyrics_guide('Eu quero cantar com você nesta noite!', voice)
        self.assertEqual(checked[0]['text'], 'Eu quero cantar com você nesta noite!')
        self.assertEqual(clocks(checked), clocks(voice))
        self.assertEqual(voice, before)
        self.assertEqual(report['checked_words'], 7)
        self.assertEqual(len(report['checks']), 7)
        self.assertEqual(report['status'], 'verified')
        self.assertGreaterEqual(report['corrected_words'], 3)

    def test_external_clocks_offsets_and_line_breaks_cannot_control_phrases(self):
        voice = acoustic('eu canto aqui e voce canta comigo')
        guides = ['[offset:30000]\n[00:01]eu canto aqui\n[00:02]e voce canta comigo',
                  '[99:99.999]eu canto aqui\n[04:18]e voce canta comigo']
        first, _ = verify_lyrics_guide(guides[0], voice)
        second, _ = verify_lyrics_guide(guides[1], voice)
        self.assertEqual(first, second)
        self.assertFalse(any(w.get('lyric_line_break') for w in first[0]['words']))
        self.assertEqual(len(split_and_wrap_segments(first)), 1)
        self.assertEqual(clocks(first), clocks(voice))
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'local.ass'
            generate_ass_karaoke(first, str(target), show_instrumental=False)
            output = target.read_text()
        self.assertIn('0:00:04.00,', output)
        self.assertNotIn('0:00:01.00,', output)

    def test_repeated_sung_chorus_can_reuse_a_single_guide_phrase(self):
        voice = acoustic('eu quero cantar com voce eu quero gastar com voce')
        checked, report = verify_lyrics_guide('eu quero cantar com você', voice)
        self.assertEqual(checked[0]['text'], 'eu quero cantar com você eu quero cantar com você')
        self.assertEqual(report['checked_words'], 10)
        self.assertEqual(report['unmatched_words'], 0)
        self.assertEqual(clocks(checked), clocks(voice))

    def test_guide_with_one_chorus_checks_all_four_sung_repetitions(self):
        voice = acoustic(' '.join(['eu quero gastar com voce'] * 4))
        checked, report = verify_lyrics_guide('eu quero cantar com você', voice)
        self.assertEqual(checked[0]['text'], ' '.join(['eu quero cantar com você'] * 4))
        self.assertEqual(report['checked_words'], 20)
        self.assertEqual(report['status'], 'verified')
        self.assertEqual(clocks(checked), clocks(voice))

    def test_unrelated_guide_keeps_whisper_text_and_reports_every_difference(self):
        voice = acoustic('fala outra coisa hoje')
        checked, report = verify_lyrics_guide('eu quero cantar com você nesta noite', voice)
        self.assertEqual(checked, voice)
        self.assertEqual(report['status'], 'unrelated')
        self.assertEqual(report['checked_words'], 4)
        self.assertEqual(report['unmatched_words'], 4)
        with tempfile.TemporaryDirectory() as folder:
            retry = Mock()
            review_lyrics_with_whisper('eu quero cantar com você nesta noite', voice, folder, retry=retry)
            retry.assert_not_called()

    def test_missing_words_are_not_inserted_without_local_recognition(self):
        voice = acoustic('eu quero com voce nesta noite')
        checked, report = verify_lyrics_guide('eu quero cantar com você nesta noite', voice)
        self.assertNotIn('cantar', checked[0]['text'])
        self.assertEqual(report['missing_guide_words'], 1)
        self.assertEqual(report['checked_words'], 6)
        self.assertEqual(clocks(checked), clocks(voice))

    def test_bounded_retry_recovers_missing_word_with_its_own_acoustic_time(self):
        voice = acoustic('eu quero com voce nesta noite')
        candidate = acoustic('eu quero cantar com voce nesta noite', start=4.2)
        retry = Mock(return_value=candidate)
        with tempfile.TemporaryDirectory() as folder:
            result, report = review_lyrics_with_whisper('eu quero cantar com você nesta noite', voice, folder, retry=retry)
            saved = json.loads((Path(folder)/'lyrics_guide_cache.json').read_text())
        retry.assert_called_once()
        self.assertIn('cantar', retry.call_args.args[0]['retry_vocabulary'])
        self.assertTrue(report['retry_selected'])
        self.assertEqual(clocks(result), clocks(candidate))
        self.assertEqual(saved['report']['checked_words'], 7)

    def test_worse_retry_keeps_first_whisper_decode(self):
        voice = acoustic('eu quero com voce nesta noite')
        with tempfile.TemporaryDirectory() as folder:
            result, report = review_lyrics_with_whisper('eu quero cantar com você nesta noite', voice, folder,
                retry=lambda _: acoustic('nada disto parece com esta musica'))
        self.assertFalse(report['retry_selected'])
        self.assertEqual(clocks(result), clocks(voice))

    def test_low_acoustic_confidence_cannot_win_by_copying_the_guide(self):
        voice = acoustic('eu quero com voce nesta noite', probability=.95)
        with tempfile.TemporaryDirectory() as folder:
            result, report = review_lyrics_with_whisper('eu quero cantar com você nesta noite', voice, folder,
                retry=lambda _: acoustic('eu quero cantar com voce nesta noite', probability=.1))
        self.assertFalse(report['retry_selected'])
        self.assertEqual(clocks(result), clocks(voice))

    def test_failed_retry_keeps_valid_words_and_can_be_retried_after_restart(self):
        voice = acoustic('eu quero com voce nesta noite')
        retry = Mock(side_effect=RuntimeError('modelo ocupado'))
        with tempfile.TemporaryDirectory() as folder:
            result, report = review_lyrics_with_whisper('eu quero cantar com você nesta noite', voice, folder, retry=retry)
            self.assertTrue(report['retry_error'])
            self.assertEqual(clocks(result), clocks(voice))
            review_lyrics_with_whisper('eu quero cantar com você nesta noite', voice, folder, retry=retry)
        self.assertEqual(retry.call_count, 2)

    def test_cancelled_retry_propagates_and_does_not_save_partial_cache(self):
        voice = acoustic('eu quero com voce nesta noite')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(InterruptedError):
                review_lyrics_with_whisper('eu quero cantar com você nesta noite', voice, folder,
                    retry=Mock(side_effect=InterruptedError('cancelado')))
            self.assertFalse((Path(folder)/'lyrics_guide_cache.json').exists())

    def test_cache_reuse_ignores_provider_clocks_but_checks_guide_and_audio(self):
        voice = acoustic('eu quero com voce nesta noite')
        retry = Mock(return_value=acoustic('eu quero cantar com voce nesta noite'))
        with tempfile.TemporaryDirectory() as folder:
            first = review_lyrics_with_whisper('[00:01]eu quero cantar com você nesta noite', voice, folder,
                context={'audio_hash':'one'}, retry=retry)
            second = review_lyrics_with_whisper('[04:58]eu quero cantar com você nesta noite', voice, folder,
                context={'audio_hash':'one'}, retry=retry)
            self.assertEqual(first, second)
            retry.assert_called_once()
            review_lyrics_with_whisper('eu quero cantar com você nesta noite', voice, folder,
                context={'audio_hash':'two'}, retry=retry)
            self.assertEqual(retry.call_count, 2)
            changed, _ = review_lyrics_with_whisper('eu quero cantar com você nesta noite especial', voice, folder,
                context={'audio_hash':'two'}, retry=retry)
            self.assertEqual(retry.call_count, 3)
            self.assertNotIn('especial', changed[0]['text'])

    def test_no_guide_keeps_the_whisper_words_and_clocks(self):
        voice = acoustic('eu canto assim')
        result, report = verify_lyrics_guide('', voice)
        self.assertEqual(result, voice)
        self.assertEqual(report['status'], 'no_guide')

    def test_empty_recognition_and_external_timed_retry_cannot_supply_lyrics(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                review_lyrics_with_whisper('[00:10]eu canto assim', [], folder)
            voice = acoustic('eu quero com voce nesta noite')
            candidate = acoustic('eu quero cantar com voce nesta noite')
            candidate[0]['synced_line'] = True
            result, report = review_lyrics_with_whisper('eu quero cantar com você nesta noite', voice, folder,
                retry=lambda _: candidate)
        self.assertTrue(report['retry_error'])
        self.assertEqual(clocks(result), clocks(voice))

    def test_fuzzy_alignment_does_not_shift_words_past_a_missing_guide_word(self):
        voice = acoustic('eu quero com voce nesta noite quero gastar junto')
        checked, report = verify_lyrics_guide('eu quero cantar com você nesta noite quero cantar junto', voice)
        self.assertEqual(checked[0]['text'], 'eu quero com você nesta noite quero cantar junto')
        self.assertEqual(report['missing_guide_words'], 1)
        self.assertEqual(clocks(checked), clocks(voice))

    def test_lrc_metadata_is_discarded_without_sorting_or_duplicate_verses(self):
        self.assertEqual(prepare_lyrics_guide('[ar:Artista]\n[offset:-800]\n[01:10][00:20]Mesmo verso\n[01:15]<01:15.20>Outra palavra'),
                         'Mesmo verso\nOutra palavra')
