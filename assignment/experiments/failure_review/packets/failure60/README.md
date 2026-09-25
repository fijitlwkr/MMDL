# 모델 실패 유형 60건 — 원문 근거 검토

현재 정책상 오답 300건 중 과목별 2건씩 추출했다(30과목, 표본추출 seed 3407). 추론 seed와 별개다. 10건씩 6개 batch이며, reference_gold를 보여주는 원인 분석용 자료다. 골드를 숨기는 답 추출 실험과 구분한다.

원문 전체와 이미지를 확인하고, labels.jsonl을 복사해 reviewer·검토 필드를 작성한다. 제공된 빈 원본은 보존한다. 자동 생성 라벨과 이전 챗의 답을 사람 라벨로 복사하지 않는다.

answer_status는 explicit(명시된 답), inferable(문맥에서 하나로 확정 가능한 답), ambiguous(복수 결론이 남음), no_answer(응답에서 답을 판단할 근거가 없음) 중 하나다. Final Answer 표기가 없어도 판단할 수 있으면 inferable로 기록한다. length 종료만으로 no_answer로 만들지 않는다. 문제를 새로 풀어서 모델이 말하지 않은 답을 보충하지 않는다. 명시적인 최종 수정이 있으면 이전 가정보다 우선한다.

human_answer는 객관식의 실제 선택지 문자, 주관식의 답 원문이다. 주관식에 평가용 A/B를 쓰지 않는다. ambiguous/no_answer일 때는 비워 둔다. evidence_quote는 모델 응답의 정확한 인용, inference_note는 문맥 추론이 필요한 경우의 근거다. reviewer와 review_status=done을 작성하기 전까지 완료 라벨로 세지 않는다.

이미지는 고정 MMMU revision에서 raw.image_indices 순서로 추출한 원본 파일이다. 각 batch 문서에 이미지와 raw_text 전문이 있다. 문서가 길어 뷰어가 생략하면 다운로드해서 전문을 읽는다. 사람이 실제로 확인한 경우에만 images_checked=true로 바꾼다.

primary_type은 아래 한 가지를 선택하고, 함께 나타난 현상은 secondary_types에 기록한다. 근거 없이 이미지·지식 오류를 단정하지 말고 uncertain을 허용한다.

| 값 | 판정 근거 |
|---|---|
| visual_reading | 실제 이미지의 문자·기호·도형 관계를 응답이 다르게 읽은 위치를 특정 |
| knowledge | 필요한 개념·사실을 잘못 적용한 명시적 서술을 특정 |
| calculation_reasoning | 입력을 읽은 뒤의 계산·논리 단계에서 잘못된 전개를 특정 |
| repetition_incomplete | 반복·자기수정이 이어지며 답 확정에 실패한 원문 근거. 단순히 길거나 length인 것만으로 분류하지 않음 |
| evaluation_issue | 모델 응답의 답과 저장 채점의 오답 판정이 어긋난다는 근거. 취합자가 기존 판정과 추가 대조 |
| uncertain | 자료만으로 원인을 구분할 수 없음. 부족한 근거를 notes에 기록 |

원인 판정은 evidence_quote와 image_evidence/diagnosis에 근거를 남긴다. 개선 아이디어는 improvement_target에 짧게 기록한다. 실제 답이 올바르게 표현됐다고 보이면 model_answer_correct=true로 기록하되, 기존 점수는 이 검토만으로 덮어쓰지 않는다. 수치 동치가 허용오차에 달렸다면 tolerance_dependent=true와 이유를 남긴다.

과목당 오답 수가 달라 60건의 단순 비율을 300건 전체 비율로 쓰지 않는다. 취합 시 과목별 오답 수/2의 가중치를 쓰고, 표본 수·선정법·미확정 수를 함께 표시한다. 이는 정책상 오답 집단의 분석이며 정책상 정답 안의 채점 오류를 추정하지 않는다. 각 과목 2건이라 과목별 실패율을 정밀하게 추정할 표본은 아니다.
