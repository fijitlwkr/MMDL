"""Conservative MMFR formatting; import the unchanged evaluation prompt functions."""
import ast
import collections
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'reference_code'))
from mmmu_pipeline.dataset import _prompt_text, build_messages

IMAGE_CONFIG = {'image': {'min_pixels': 1003520, 'max_pixels': 4014080}}
LABELS = 'ABCDEFGH'
STYLES = [
    ('dot', r'([A-Ha-h])[.．、]'),
    ('rparen', r'([A-Ha-h])\)'),
    ('paren', r'\(([A-Ha-h])\)'),
    ('colon', r'([A-Ha-h])[:：]'),
    ('bracket', r'\[([A-Ha-h])\]'),
]


def stem_clean(text):
    return re.sub(r'\s*(?:Choices|Options)\s*[:：]?\s*$', '', text, flags=re.I).rstrip()


def option_clean(text):
    return re.sub(r'\s*Answer with the letter\.?\s*$', '', text, flags=re.I).strip()


def split_options(question):
    # A trailing literal list preserves explicit option values; no choices are invented.
    for match in re.finditer(r'\[\s*[\'\"]', question):
        try:
            values = ast.literal_eval(question[match.start():].strip())
        except (ValueError, SyntaxError):
            continue
        if not isinstance(values, list) or not 2 <= len(values) <= len(LABELS) or not all(isinstance(v, str) for v in values):
            continue
        labelled = [re.match(r'^\s*([A-Ha-h])[:.．、)]\s*(.*)$', v, re.S) for v in values]
        if all(labelled):
            if ''.join(m.group(1).upper() for m in labelled) != LABELS[:len(values)]:
                return None, {}, 'ambiguous_literal_labels'
            values = [m.group(2).strip() for m in labelled]
        elif any(labelled):
            return None, {}, 'mixed_literal_labels'
        return stem_clean(question[:match.start()]), dict(zip(LABELS, values)), 'literal_list'

    # Some MMFR lists have unescaped apostrophes or omit string quotes entirely.
    for match in re.finditer(r'[\[(]\s*[\'\"]?A[:.]\s+', question):
        block = question[match.start():].strip()
        if block[-1:] not in [']', ')']:
            continue
        body = block[1:-1]
        marks = list(re.finditer(r'(?:^|[,;]\s*)[\'\"]?([A-H])[:.]\s*', body))
        if not 2 <= len(marks) <= len(LABELS) or ''.join(m.group(1) for m in marks) != LABELS[:len(marks)]:
            continue
        opts = {}
        for j, mark in enumerate(marks):
            end = marks[j+1].start() if j+1 < len(marks) else len(body)
            value = body[mark.end():end].strip()
            if value.endswith(('\"', "'")):
                value = value[:-1].rstrip()
            opts[mark.group(1)] = value
        if all(opts.values()):
            return stem_clean(question[:match.start()]), opts, 'explicit_bracket_labels'

    for mode, prefix in [('line', r'(?m)^[ \t]*'), ('inline', r'(?<![A-Za-z0-9_])')]:
        candidates = []
        for style, label in STYLES:
            avoid_nested = r'(?<!\()' if style == 'rparen' else ''
            marks = list(re.finditer(prefix + avoid_nested + label + r'[ \t]*', question))
            for i, mark in enumerate(marks):
                if mark.group(1).upper() != 'A':
                    continue
                block = marks[i:]
                if len(block) < 2 or len(block) > len(LABELS):
                    continue
                if ''.join(m.group(1).upper() for m in block) != LABELS[:len(block)]:
                    continue
                opts = {}
                for j, m in enumerate(block):
                    end = block[j + 1].start() if j + 1 < len(block) else len(question)
                    opts[m.group(1).upper()] = option_clean(question[m.end():end])
                if all(opts.values()):
                    candidates.append((stem_clean(question[:mark.start()]), opts, mode + '_' + style))
        unique = {(x[0], tuple(x[1].items())): x for x in candidates}
        if len(unique) == 1:
            return next(iter(unique.values()))
        if len(unique) > 1:
            return None, {}, 'ambiguous_blocks'

    bare = re.search(r'(?im)^\s*(?:Choices|Options)\s*[:：]\s*\n', question)
    if bare:
        values = [x.strip() for x in question[bare.end():].splitlines() if x.strip()]
        if 2 <= len(values) <= len(LABELS):
            return question[:bare.start()].rstrip(), dict(zip(LABELS, values)), 'bare_choices'
        return None, {}, 'ambiguous_bare_choices'
    if any(re.search(r'(?m)^[ \t]*' + label + r'[ \t]*', question) for _, label in STYLES):
        return None, {}, 'partial_or_empty_options'
    if re.search(r'(?:\bA[.)：:]\s+.+\bB[.)：:]|\(A\).+\(B\))', question, re.S):
        return None, {}, 'unparsed_option_markers'
    return question, {}, 'open_ended'


def content_key(value):
    # Strip presentation delimiters only; do not compute or change mathematical values.
    value = value.strip()
    wrappers = [('$', '$'), ('\\(', '\\)'), ('\\[', '\\]')]
    changed = True
    while changed:
        changed = False
        for left, right in wrappers:
            if value.startswith(left) and value.endswith(right) and len(value) > len(left) + len(right):
                value = value[len(left):-len(right)].strip()
                changed = True
                break
    value = re.sub(r'\s+', ' ', value).strip().removesuffix('.')
    if '\\' in value:
        # TeX spacing is presentation, but atom boundaries and braces remain significant.
        return tuple(re.findall(r'\\[A-Za-z]+|\\.|[A-Za-z]+|\d+(?:\.\d+)?|[^\s]', value))
    return value


def answer_letter(answer, options):
    if not options:
        return answer, 'open_ended'
    letter = re.fullmatch(r'\s*(?:[Oo]ption\s+)?\(?([A-Ha-h])\)?[.。]?\s*', answer)
    if letter and letter.group(1).upper() in options:
        return letter.group(1).upper(), 'explicit_letter'
    if re.fullmatch(r'\s*[A-Ha-h](?:\s*(?:[,;、]|and)\s*[A-Ha-h])+\s*', answer):
        labels = re.findall(r'[A-H]', answer.upper().replace('AND', ','))
        if all(label in options for label in labels):
            return ', '.join(labels), 'explicit_letter_sequence'
    labelled = re.fullmatch(r'\s*([A-Ha-h])[.、:：)]\s*(.+?)\s*', answer, re.S)
    if labelled and labelled.group(1).upper() in options:
        key = labelled.group(1).upper()
        if content_key(labelled.group(2)) == content_key(options[key]):
            return key, 'explicit_letter_and_matching_content'
    matches = [k for k, v in options.items() if content_key(v) == content_key(answer)]
    if len(matches) == 1:
        return matches[0], 'unique_content_match'
    return None, 'non_unique_or_unmatched_content'


def prepare_one(row, overrides, reviews=None):
    review = (reviews or {}).get(str(row['row']))
    if review:
        assert review['source']==row['source'] and review['id']==row['id']
        assert review['question_sha256']==hashlib.sha256(row['question'].encode()).hexdigest()
        assert review['image_sha256']==row['image_sha256']
        if review['decision']=='exclude':
            return dict(row=row['row'],source=row['source'],id=row['id'],role=row['role'],
                        option_style='manually_reviewed_unrecoverable',options={},original_answer=row['answer'],
                        format_status='excluded',exclude_reason='unrecoverable_source_format',
                        recovery_reason=review['reason'],recovery_status='reviewed_exclude')
    number = 0
    def marker(match):
        nonlocal number
        number += 1
        if match.group(1):
            assert int(match.group(1)) == number
        return '<image ' + str(number) + '>'
    normalized_question = re.sub(r'<image(?:\s+(\d+))?>', marker, row['question'], flags=re.I)
    assert number == len(row['images'])
    override = overrides.get(str(row['row']))
    if review and review['mode'] in ['open_ended','visual_options','text_options']:
        stem=normalized_question
        if review['mode']=='text_options':
            if 'stem_override' in review:
                stem=review['stem_override']
            elif 'remove_question_block' in review:
                assert row['question'].count(review['remove_question_block'])==1
                stem=row['question'].replace(review['remove_question_block'],'',1)
            elif 'options_start' in review:
                cut=row['question'].index(review['options_start'])
                stem=row['question'][:cut]
            else:
                raise AssertionError('Text option recovery needs an explicit source boundary')
            assert len(row['images'])==1
            stem=re.sub(r'<image(?:\s+\d+)?>','<image 1>',stem,flags=re.I)
            options=review['options']
        elif review['mode']=='visual_options':
            labels=review['labels']
            assert labels==LABELS[:len(labels)] and len(labels)>=2
            options={label:('Panel ('+label.lower()+') in the image.' if review.get('label_case')=='lower' else 'Option '+label+' in the image.') for label in labels}
        else:
            options={}
        style='reviewed_'+review['mode']
    elif override:
        assert (override['source'], override['id']) == (row['source'], row['id'])
        assert override['question_sha256'] == hashlib.sha256(row['question'].encode()).hexdigest()
        stem, options, style = normalized_question, {}, 'reviewed_open_ended'
    else:
        stem, options, style = split_options(normalized_question)
    result = dict(row=row['row'], source=row['source'], id=row['id'], role=row['role'],
                  option_style=style, options=options, original_answer=row['answer'])
    if review:
        result.update(recovery_status='reviewed_keep',recovery_reason=review['reason'],quality_flags=review.get('quality_flags',[]))
    if stem is None:
        return dict(result, format_status='excluded', exclude_reason='option_parse_fail')
    if not options and not (review and review['mode']=='open_ended') and re.fullmatch(r'\s*[A-Ha-h](?:\s*[,;]\s*[A-Ha-h])*\s*', row['answer']):
        explicit_mc = re.search(r'\bwhich\s+(?:one\s+)?of\s+(?:the\s+)?following\b', stem, re.I)
        named_label = re.search(r'\b(?:which|what)\s+(?:point|curve|line|period)\b|\b(?:which|what)\b.{0,90}\b(?:label|letter|labelled|labeled)\b', stem, re.I|re.S)
        if explicit_mc or not named_label:
            return dict(result, format_status='excluded', exclude_reason='option_parse_fail',
                        option_parse_detail='letter_answer_without_separable_text_options')
        result['option_style'] = 'open_ended_named_plot_label'
    final, answer_method = answer_letter(row['answer'], options)
    if review and 'final_answer_override' in review:
        final=review['final_answer_override']
        assert final in options
        answer_method='manually_verified_unique_content_match'
    result.update(final_answer=final, answer_method=answer_method)
    if final is None:
        return dict(result, format_status='excluded', exclude_reason='answer_letter_fail')
    tail = row['solution_after_think_raw']
    tags = list(re.finditer(r'<answer>(.*?)</answer>', tail, re.S))
    append_missing = not tags and not ('<answer>' in tail or '</answer>' in tail) and review and review.get('allow_missing_tag')
    if not append_missing and (not tags or tail.count('<answer>') != len(tags) or tail.count('</answer>') != len(tags)):
        return dict(result, format_status='excluded', exclude_reason='answer_tag_fail', answer_tag_detail='missing_or_unbalanced')
    if len(tags) > 1:
        equivalent = []
        for tag in tags:
            raw = tag.group(1).strip()
            label, _ = answer_letter(raw, options)
            key = content_key(label if label is not None else raw)
            if isinstance(key, str) and re.fullmatch('[A-Ha-h]', key):
                key = key.upper()
            equivalent.append(key)
        if len(set(equivalent)) != 1 and int(row['row']) != 1541116 and not (review and review.get('allow_multiple_tags')):
            return dict(result, format_status='excluded', exclude_reason='answer_tag_fail', answer_tag_detail='different_multiple_answers')
    # Preserve all prose; unwrap earlier duplicate tags and replace the last tag only.
    chunks = []
    pos = 0
    for i, tag in enumerate(tags):
        chunks.append(tail[pos:tag.start()])
        chunks.append('Final Answer: ' + final if i == len(tags)-1 else tag.group(1))
        pos = tag.end()
    chunks.append(tail[pos:])
    assistant = ''.join(chunks)
    if append_missing:
        assistant=tail.rstrip()+'\n\nFinal Answer: '+final
    if '<think>' in assistant or '</think>' in assistant or '<answer>' in assistant or '</answer>' in assistant:
        return dict(result, format_status='excluded', exclude_reason='answer_tag_fail', answer_tag_detail='remaining_structure_tags')
    prompt = _prompt_text({'question': stem}, options)
    user = build_messages({'image_paths': row['images'], 'prompt': prompt}, IMAGE_CONFIG)
    for path in row['images']:
        assert not Path(path).is_absolute() and (ROOT/path).resolve().is_relative_to(ROOT)
    return dict(result, format_status='pass', exclude_reason='', question_stem=stem, prompt=prompt,
                messages=user+[{'role':'assistant','content':assistant}],
                messages_e2=user+[{'role':'assistant','content':'Final Answer: '+final}],
                answer_tag_count=len(tags), answer_tag_handling='reviewed_missing_tag_append_gold' if append_missing else ('single_replace' if len(tags)==1 else 'reviewed_multiple_tags_unwrapped'))


def diagnostic():
    rows = [json.loads(line) for line in (ROOT / 'handoff_rows.jsonl').read_text(encoding='utf-8').splitlines()]
    counts = collections.Counter()
    pending = []
    for x in rows:
        stem, options, style = split_options(x['question'])
        answer, method = answer_letter(x['answer'], options) if stem is not None else (None, 'option_parse_fail')
        tags = re.findall(r'<answer>(.*?)</answer>', x['solution_after_think_raw'], re.S)
        counts[(style, method)] += 1
        issues = []
        if stem is None or answer is None:
            issues.append(method)
        if len(tags) != 1:
            issues.append('answer_tag_count_' + str(len(tags)))
        if not options and re.fullmatch(r'\s*[A-Ha-h]\s*', x['answer']):
            issues.append('open_ended_letter_review')
        if issues:
            pending.append(dict(row=x['row'], role=x['role'], source=x['source'], id=x['id'], issues=issues,
                                style=style, options=options, question=x['question'], answer=x['answer'],
                                solution_after_think_raw=x['solution_after_think_raw']))
    (ROOT / 'cache/stage47_format_pending.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False)+'\n' for x in pending), encoding='utf-8')
    report = {'counts': [{'style':a,'method':b,'n':n} for (a,b),n in counts.most_common()],
              'pending_rows':len(pending),'pending_issue_counts':dict(collections.Counter(i for x in pending for i in x['issues']))}
    (ROOT / 'stage47_format_diagnostic.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


def self_check():
    q, opts, _ = split_options('Question?\nA. 3\nB. 4\nC. 5\nD. 6')
    assert q == 'Question?' and opts == {'A':'3','B':'4','C':'5','D':'6'}
    assert answer_letter('4', opts) == ('B', 'unique_content_match')
    assert answer_letter('B, D', opts) == ('B, D', 'explicit_letter_sequence')
    assert answer_letter('A, A', opts) == ('A, A', 'explicit_letter_sequence')
    assert answer_letter('4', {'A':'4','B':'4'})[0] is None
    assert answer_letter('0.5', {'A':'1/2','B':'1'})[0] is None
    assert split_options("Question? ['A: 3', 'B: 4']")[1] == {'A':'3','B':'4'}
    assert split_options('Question? (a) one (b) two')[1] == {'A':'one','B':'two'}
    assert split_options('Question?\nChoices:\nA\nT\nM\nP')[1] == {'A':'A','B':'T','C':'M','D':'P'}
    assert split_options('What is the mean of A and B?')[2] == 'open_ended'
    assert _prompt_text({'question':'x'}, {'A':'one','B':'two'}).encode('utf-8') == b'Question: x\nOptions:\nA. one\nB. two\nPlease select the correct answer from the options above.'
    msg = build_messages({'image_paths':['images/x.png'],'prompt':'Question: x'}, IMAGE_CONFIG)
    assert msg[0]['content'][0]['type'] == 'image' and msg[0]['content'][-1]['text'] == 'Question: x'


if __name__ == '__main__':
    self_check()
    diagnostic()
