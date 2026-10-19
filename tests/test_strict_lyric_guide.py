"""Regressions for the words lost by the retired strict guide filter."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from lyric_guide import (GUIDE_POLICY_VERSION, guide_correction_candidate,
                         review_lyrics_with_whisper, verify_lyrics_guide)


def acoustic(text, start=4., step=.4):
    words = [dict(word=' ' + token, start=start + index * step,
                  end=start + index * step + .3, probability=.9)
             for index, token in enumerate(text.split())]
    return [dict(start=words[0]['start'], end=words[-1]['end'], text=text, words=words)] if words else []


def text(segments):
    return ' '.join(segment['text'] for segment in segments)


def clocks(segments):
    return [(word['start'], word['end']) for segment in segments for word in segment['words']]


class ConservativeGuideTests(unittest.TestCase):
    def test_unmatched_words_at_edges_and_inside_are_preserved(self):
        source = acoustic('abertura eu canto improviso aqui encerramento')
        result, report = verify_lyrics_guide('eu canto aqui', source)
        self.assertEqual(result, source)
        self.assertEqual(report['checked_words'], 6)
        self.assertEqual(report['unmatched_words'], 3)

    def test_unrelated_or_reversed_guide_does_not_empty_the_recording(self):
        for guide, heard in [('eu canto aqui', 'uma gravação completamente diferente'),
                             ('a luz da noite ilumina casa', 'casa ilumina noite luz')]:
            with self.subTest(guide=guide):
                source = acoustic(heard)
                result, _ = verify_lyrics_guide(guide, source)
                self.assertEqual(result, source)

    def test_a_lone_common_word_survives_without_two_anchors(self):
        source = acoustic('você')
        result, _ = verify_lyrics_guide('eu canto com você', source)
        self.assertEqual(result, source)

    def test_strong_contextual_correction_preserves_every_word_clock(self):
        guide = 'eu quero cantar com você nesta noite'
        source = acoustic('eu quero gastar com voce nesta noite')
        before = copy.deepcopy(source)
        result, report = verify_lyrics_guide(guide, source)
        self.assertEqual(text(result), guide)
        self.assertEqual(clocks(result), clocks(source))
        self.assertEqual(source, before)
        self.assertEqual(report['correction_proposals'][0]['guide'], 'cantar')
        self.assertEqual(guide_correction_candidate(guide, source[0]['words']), guide.split())

    def test_short_unique_spelling_needs_a_local_neighbor(self):
        source = acoustic('hello word')
        self.assertEqual(guide_correction_candidate('hello world', source[0]['words']), ['hello', 'world'])
        result, _ = verify_lyrics_guide('hello world', source)
        self.assertEqual(text(result), 'hello world')
        self.assertEqual(clocks(result), clocks(source))
        isolated = acoustic('word')
        self.assertEqual(verify_lyrics_guide('world', isolated)[0], isolated)
        self.assertIsNone(guide_correction_candidate('world', isolated[0]['words'], allow_distant=True))

    def test_distinct_context_selects_the_appropriate_similar_phrase(self):
        guide = 'eu quero cantar com você\nela disse que vai contar tudo'
        source = acoustic('eu quero centar com voce')
        result, _ = verify_lyrics_guide(guide, source)
        self.assertEqual(text(result), 'eu quero cantar com você')
        self.assertEqual(clocks(result), clocks(source))

    def test_equally_plausible_phrases_keep_the_original_word(self):
        guide = 'eu quero cantar com você\neu quero contar com você'
        source = acoustic('eu quero centar com voce')
        result, report = verify_lyrics_guide(guide, source)
        self.assertEqual(text(result), 'eu quero centar com você')
        self.assertEqual(clocks(result), clocks(source))
        self.assertEqual(report['ambiguous_words'], 1)
        self.assertEqual(report['checks'][2]['status'], 'ambiguous')
        for distant in (False, True):
            self.assertIsNone(guide_correction_candidate(guide, source[0]['words'], allow_distant=distant))

    def test_distant_substitution_is_only_an_explicit_acoustic_hypothesis(self):
        guide = 'eu quero cantar com você nesta noite'
        source = acoustic('eu quero viver com voce nesta noite')
        result, _ = verify_lyrics_guide(guide, source)
        self.assertEqual(text(result), 'eu quero viver com você nesta noite')
        self.assertIsNone(guide_correction_candidate(guide, source[0]['words']))
        self.assertEqual(guide_correction_candidate(guide, source[0]['words'], allow_distant=True), guide.split())

    def test_distant_proposal_cannot_choose_between_equal_phrase_contexts(self):
        guide = 'eu quero cantar com você\neu quero viver com você'
        source = acoustic('eu quero banana com voce')
        self.assertIsNone(guide_correction_candidate(guide, source[0]['words'], allow_distant=True))

    def test_missing_inner_word_is_not_inserted_or_shifted_onto_a_neighbor(self):
        guide = 'eu quero cantar com você nesta noite'
        source = acoustic('eu quero com voce nesta noite')
        result, report = verify_lyrics_guide(guide, source)
        self.assertEqual(text(result), 'eu quero com você nesta noite')
        self.assertEqual(clocks(result), clocks(source))
        self.assertEqual(report['missing_guide_words'], 1)
        self.assertIsNone(guide_correction_candidate(guide, source[0]['words'], allow_distant=True))

    def test_extra_word_does_not_duplicate_an_adjacent_match(self):
        guide = 'eu quero cantar com você'
        source = acoustic('eu quero cantarr cantar com voce')
        result, _ = verify_lyrics_guide(guide, source)
        self.assertEqual(text(result), 'eu quero cantarr cantar com você')
        self.assertEqual(clocks(result), clocks(source))
        self.assertIsNone(guide_correction_candidate(guide, source[0]['words'], allow_distant=True))

    def test_sung_repetitions_survive_without_creating_printed_repetitions(self):
        guide = 'eu quero cantar com você'
        source = acoustic(' '.join(['eu quero gastar com voce'] * 4))
        result, _ = verify_lyrics_guide(guide, source)
        self.assertEqual(text(result), ' '.join([guide] * 4))
        self.assertEqual(clocks(result), clocks(source))
        line = 'deixe uma luz acesa'
        one_occurrence = acoustic(line)
        self.assertEqual(verify_lyrics_guide(line + '\n' + line, one_occurrence)[0], one_occurrence)
        single_word = acoustic('ah improviso ah')
        self.assertEqual(verify_lyrics_guide('ah', single_word)[0], single_word)

    def test_contraction_fragments_keep_their_original_intervals(self):
        guide = "My words I'll keep them down"
        source = acoustic("My words I 'll keep them down")
        source[0]['words'][3]['word'] = "'ll"
        result, _ = verify_lyrics_guide(guide, source)
        self.assertEqual(text(result), guide)
        self.assertEqual(clocks(result), clocks(source))
        self.assertIsNone(guide_correction_candidate(guide, source[0]['words'], allow_distant=True))

    def test_manual_phrase_spans_survive_without_synthetic_word_clocks(self):
        for phrase in ('Minha revisão completa', 'eu canto improviso aqui', 'aqui canto eu'):
            with self.subTest(phrase=phrase):
                source = [dict(start=8, end=14, text=phrase,
                               words=[dict(word=phrase, start=8, end=14)])]
                result, _ = verify_lyrics_guide('eu canto aqui', source)
                self.assertEqual(result, source)
                self.assertIsNone(guide_correction_candidate('eu canto aqui', source[0]['words'], allow_distant=True))

    def test_external_lrc_clocks_do_not_change_local_clocks_or_proposals(self):
        source = acoustic('hello word', start=42)
        first, _ = verify_lyrics_guide('[00:01]hello world', source)
        second, _ = verify_lyrics_guide('[99:59]hello world', source)
        self.assertEqual(first, second)
        self.assertEqual(clocks(first), clocks(source))
        self.assertEqual(guide_correction_candidate('[00:01]hello world', source[0]['words']),
                         guide_correction_candidate('[99:59]hello world', source[0]['words']))

    def test_a_long_rest_cannot_supply_an_adjacent_correction_anchor(self):
        source = acoustic('hello word')
        source[0]['words'][1].update(start=18, end=18.3)
        source[0]['end'] = 18.3
        self.assertEqual(verify_lyrics_guide('hello world', source)[0], source)
        self.assertIsNone(guide_correction_candidate('hello world', source[0]['words'], allow_distant=True))

    def test_old_strict_cache_cannot_restore_a_truncated_result(self):
        guide = 'eu canto aqui'
        source = acoustic('eu canto improviso aqui')
        signature = hashlib.sha256(json.dumps(dict(version=2, guide=guide, segments=source,
            context={}), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / 'lyrics_guide_cache.json'
            cache.write_text(json.dumps(dict(signature=signature, segments=acoustic(guide),
                                           report=dict(version=2))), encoding='utf-8')
            result, report = review_lyrics_with_whisper(guide, source, folder)
        self.assertEqual(result, source)
        self.assertEqual(report['version'], GUIDE_POLICY_VERSION)

    def test_output_is_idempotent_and_hypotheses_do_not_mutate_input(self):
        guide = 'eu quero cantar com você'
        source = acoustic('extra eu quero gastar com voce improviso')
        before = copy.deepcopy(source)
        candidate = guide_correction_candidate(guide, source[0]['words'])
        self.assertEqual(len(candidate), len(source[0]['words']))
        self.assertEqual((candidate[0], candidate[-1]), ('extra', 'improviso'))
        first, _ = verify_lyrics_guide(guide, source)
        second, _ = verify_lyrics_guide(guide, first)
        self.assertEqual(first, second)
        self.assertEqual(source, before)


if __name__ == '__main__':
    unittest.main()
