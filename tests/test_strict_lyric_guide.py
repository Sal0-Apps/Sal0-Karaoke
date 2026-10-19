"""The final guide contract must also hold for old caches and manual drafts."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from lyric_guide import enforce_guide_text, normalize_word, GUIDE_POLICY_VERSION


def acoustic(text, start=4., step=.4):
    words = [dict(word=' ' + token, start=start + index * step,
                  end=start + index * step + .3, probability=.9)
             for index, token in enumerate(text.split())]
    return [dict(start=words[0]['start'], end=words[-1]['end'], text=text, words=words)] if words else []


def text(segments):
    return ' '.join(segment['text'] for segment in segments)


def clocks(segments):
    return [(word['start'], word['end']) for segment in segments for word in segment['words']]


class StrictGuideTests(unittest.TestCase):
    def assert_contract(self, guide, result):
        from lyric_guide import prepare_lyrics_guide
        canonical = set(prepare_lyrics_guide(guide).split())
        self.assertTrue(all(word['word'].strip() in canonical for segment in result for word in segment['words']))

    def test_exact_phrase_preserves_clocks_and_input(self):
        source = acoustic('eu canto aqui')
        before = copy.deepcopy(source)
        result, report = enforce_guide_text('eu canto aqui', source)
        self.assertEqual(text(result), 'eu canto aqui')
        self.assertEqual(clocks(result), clocks(source))
        self.assertEqual(source, before)
        self.assertEqual(report['status'], 'verified')
        self.assertEqual(report['version'], GUIDE_POLICY_VERSION)

    def test_unknown_words_at_both_edges_and_inside_never_survive(self):
        guide = 'eu canto aqui'
        source = acoustic('fantasma eu canto bobagem aqui encerramento')
        result, report = enforce_guide_text(guide, source)
        self.assertEqual(text(result), guide)
        self.assertEqual(report['removed_words'], 3)
        self.assertEqual(clocks(result), [clocks(source)[index] for index in (1, 2, 4)])
        self.assert_contract(guide, result)

    def test_unrelated_guide_yields_empty_instead_of_replacing_the_song(self):
        result, report = enforce_guide_text('eu canto aqui', acoustic('uma gravação completamente diferente'))
        self.assertEqual(result, [])
        self.assertEqual(report['status'], 'unrelated')
        self.assertEqual(report['removed_words'], 4)

    def test_dictionary_membership_without_phrase_order_is_insufficient(self):
        guide = 'a luz da noite ilumina casa'
        result, report = enforce_guide_text(guide, acoustic('casa ilumina noite luz'))
        self.assertEqual(result, [])
        self.assertEqual(report['removed_words'], 4)

    def test_similar_word_uses_two_local_anchors_and_its_original_clock(self):
        guide = 'eu quero cantar com você nesta noite'
        source = acoustic('eu quero gastar com voce nesta noite')
        result, report = enforce_guide_text(guide, source)
        self.assertEqual(text(result), guide)
        self.assertEqual(clocks(result), clocks(source))
        self.assertGreaterEqual(report['corrected_words'], 2)
        self.assert_contract(guide, result)

    def test_context_selects_between_similar_phrases(self):
        guide = 'eu quero cantar com você\nela disse que vai contar tudo'
        result, _ = enforce_guide_text(guide, acoustic('eu quero centar com voce'))
        self.assertEqual(text(result), 'eu quero cantar com você')

    def test_ambiguous_similar_word_is_removed_but_exact_context_survives(self):
        guide = 'eu quero cantar com você\neu quero contar com você'
        result, report = enforce_guide_text(guide, acoustic('eu quero centar com voce'))
        self.assertEqual(text(result), 'eu quero com você')
        self.assertEqual(report['ambiguous_words'], 1)
        self.assert_contract(guide, result)

    def test_lone_common_word_does_not_authorize_an_unrelated_fragment(self):
        result, _ = enforce_guide_text('eu canto com você', acoustic('você'))
        self.assertEqual(result, [])

    def test_missing_guide_words_are_never_inserted(self):
        guide = 'eu quero cantar com você nesta noite'
        source = acoustic('eu quero com voce nesta noite')
        result, _ = enforce_guide_text(guide, source)
        self.assertEqual(text(result), 'eu quero com você nesta noite')
        self.assertEqual(clocks(result), clocks(source))

    def test_a_printed_chorus_can_be_reused_at_distinct_observed_times(self):
        guide = 'eu quero cantar com você'
        source = acoustic('eu quero cantar com voce', 1) + acoustic('eu quero cantar com voce', 10)
        result, _ = enforce_guide_text(guide, source)
        self.assertEqual(text(result), guide + ' ' + guide)
        self.assertEqual(clocks(result), clocks(source))

    def test_printed_repetition_never_creates_an_unobserved_occurrence(self):
        line = 'deixe uma luz acesa'
        source = acoustic(line)
        result, _ = enforce_guide_text(line + '\n' + line, source)
        self.assertEqual(text(result), line)
        self.assertEqual(clocks(result), clocks(source))

    def test_single_word_refrain_keeps_only_exact_separate_observations(self):
        source = acoustic('ah absurdo ah')
        result, report = enforce_guide_text('ah', source)
        self.assertEqual(text(result), 'ah ah')
        self.assertEqual(report['removed_words'], 1)

    def test_contiguous_contraction_fragments_merge_without_retiming_neighbors(self):
        guide = "My words I'll keep them down"
        source = acoustic("My words I 'll keep them down")
        result, report = enforce_guide_text(guide, source)
        self.assertEqual(text(result), guide)
        self.assertEqual(report['merged_words'], 1)
        self.assertEqual(clocks(result), clocks(source)[:2] + [(clocks(source)[2][0], clocks(source)[3][1])] + clocks(source)[4:])
        self.assert_contract(guide, result)

    def test_contraction_fragments_separated_in_time_cannot_copy_a_full_word(self):
        guide = "My words I'll keep them down"
        source = acoustic("My words I 'll keep them down")
        for word in source[0]['words'][3:]:
            word['start'] += .6
            word['end'] += .6
        result, report = enforce_guide_text(guide, source)
        self.assertNotIn("I'll", text(result))
        self.assertEqual(report['merged_words'], 0)
        self.assert_contract(guide, result)

    def test_outdated_cache_flags_and_segment_text_cannot_bypass_the_gate(self):
        source = acoustic('eu canto invasora aqui')
        source[0].update(text='OUTDATED TEXT', synced_line=True, acoustic_animation=True,
                         animation_words=[dict(word='forbidden')], guide_verified=True)
        result, report = enforce_guide_text('eu canto aqui', source)
        self.assertEqual(text(result), 'eu canto aqui')
        self.assertNotIn('animation_words', result[0])
        self.assertNotIn('synced_line', result[0])
        self.assertEqual(report['removed_words'], 1)

    def test_lrc_clock_hints_do_not_move_or_insert_any_word(self):
        source = acoustic('eu canto aqui', start=42)
        first, _ = enforce_guide_text('[00:01]eu canto aqui', source)
        second, _ = enforce_guide_text('[99:59]eu canto aqui', source)
        self.assertEqual(first, second)
        self.assertEqual(clocks(first), clocks(source))

    def test_invalid_and_duplicate_clocks_are_rejected_without_synthetic_times(self):
        source = acoustic('eu canto aqui')
        source[0]['words'] += [copy.deepcopy(source[0]['words'][1]),
                              dict(word=' eu', start=float('nan'), end=20),
                              dict(word=' eu', start=20, end=19)]
        result, report = enforce_guide_text('eu canto aqui', source)
        self.assertEqual(text(result), 'eu canto aqui')
        self.assertEqual(report['invalid_words'], 3)

    def test_no_guide_preserves_all_existing_text_and_metadata(self):
        source = acoustic('texto sem nenhuma restrição')
        source[0]['manual_note'] = 'keep'
        result, report = enforce_guide_text('', source)
        self.assertEqual(result, source)
        self.assertEqual(report['status'], 'no_guide')
        self.assertIsNot(result, source)

    def test_manual_phrase_retains_one_interval_without_inventing_word_clocks(self):
        source = [dict(start=8, end=14, text='Minha revisão completa', words=[
            dict(word='Minha revisão completa', start=8, end=14)])]
        result, report = enforce_guide_text('Minha revisão completa', source)
        self.assertEqual(text(result), 'Minha revisão completa')
        self.assertEqual(len(result[0]['words']), 1)
        self.assertEqual(clocks(result), [(8, 14)])
        self.assertEqual(report['phrase_spans'], 1)

    def test_partial_or_reversed_manual_phrase_cannot_reuse_an_entire_line_clock(self):
        for phrase in ('eu canto invasora aqui', 'aqui canto eu'):
            with self.subTest(phrase=phrase):
                source = [dict(start=8, end=14, text=phrase, words=[dict(word=phrase, start=8, end=14)])]
                result, report = enforce_guide_text('eu canto aqui', source)
                self.assertEqual(result, [])
                self.assertEqual(report['rejected_spans'], 1)

    def test_manual_phrase_and_neighboring_word_share_lexical_context(self):
        source = [dict(start=8, end=11, text='eu canto aqui', words=[
            dict(word='eu canto', start=8, end=10), dict(word=' aqui', start=10.5, end=11)])]
        result, _ = enforce_guide_text('eu canto aqui', source)
        self.assertEqual(text(result), 'eu canto aqui')
        self.assertEqual(clocks(result), [(8, 10), (10.5, 11)])

    def test_slow_phrase_with_a_short_musical_rest_keeps_real_word_clocks(self):
        source = acoustic('eu canto aqui', step=2.)
        result, _ = enforce_guide_text('eu canto aqui', source)
        self.assertEqual(text(result), 'eu canto aqui')
        self.assertEqual(clocks(result), clocks(source))

    def test_gate_is_idempotent_for_cached_words_ambiguity_and_atomic_phrases(self):
        cases = [
            ('eu canto aqui', acoustic('extra eu canto invasora aqui')),
            ('eu quero cantar com você\neu quero contar com você', acoustic('eu quero centar com voce')),
            ("My words I'll keep them down", acoustic("My words I 'll keep them down")),
            ('Minha revisão completa', [dict(start=8, end=14, text='Minha revisão completa', words=[
                dict(word='Minha revisão completa', start=8, end=14)])]),
        ]
        for guide, source in cases:
            with self.subTest(guide=guide):
                first, _ = enforce_guide_text(guide, source)
                second, _ = enforce_guide_text(guide, first)
                self.assertEqual(first, second)

    def test_long_recording_checks_corrections_and_extras_across_analysis_windows(self):
        line = 'eu quero cantar com você nesta noite de chuva e vento'
        guide = '\n'.join([line] * 7)
        heard = 'eu quero gastar com voce nesta noite de chuva e vento'
        source = acoustic(' '.join([heard + (' invasora' if index % 3 == 0 else '') for index in range(7)]))
        result, report = enforce_guide_text(guide, source)
        self.assertEqual(text(result), ' '.join([line] * 7))
        self.assertEqual(report['removed_words'], 3)
        self.assert_contract(guide, result)


if __name__ == '__main__':
    unittest.main()
