# 게이트 변경 18건 — 블라인드 답 판단

객관식 15건·주관식 3건이다. 주관식 53건 전체 검토는 이번 범위에서 제외했다. 6건씩 3개 batch로 나눴다.

이 ZIP에는 gold·기존 파서·Judge 답·정오를 넣지 않았다. 검토자는 이 ZIP만 받고, 저장소의 원본 raw·채점 결과·coordinator 대조표는 라벨 확정 뒤 확인한다. 이미 같은 문항의 정답/판정을 본 경우 prior_exposure=true와 notes에 남긴다. 이 방식은 배포 절차상의 블라인드이며 저장소 파일의 접근 통제는 아니다.

원문 전체와 이미지를 확인하고, labels.jsonl을 복사해 reviewer·검토 필드를 작성한다. 제공된 빈 원본은 보존한다. 자동 생성 라벨과 이전 챗의 답을 사람 라벨로 복사하지 않는다.

answer_status는 explicit(명시된 답), inferable(문맥에서 하나로 확정 가능한 답), ambiguous(복수 결론이 남음), no_answer(응답에서 답을 판단할 근거가 없음) 중 하나다. Final Answer 표기가 없어도 판단할 수 있으면 inferable로 기록한다. length 종료만으로 no_answer로 만들지 않는다. 문제를 새로 풀어서 모델이 말하지 않은 답을 보충하지 않는다. 명시적인 최종 수정이 있으면 이전 가정보다 우선한다.

human_answer는 객관식의 실제 선택지 문자, 주관식의 답 원문이다. 주관식에 평가용 A/B를 쓰지 않는다. ambiguous/no_answer일 때는 비워 둔다. evidence_quote는 모델 응답의 정확한 인용, inference_note는 문맥 추론이 필요한 경우의 근거다. reviewer와 review_status=done을 작성하기 전까지 완료 라벨로 세지 않는다.

이미지는 고정 MMMU revision에서 raw.image_indices 순서로 추출한 원본 파일이다. 각 batch 문서에 이미지와 raw_text 전문이 있다. 문서가 길어 뷰어가 생략하면 다운로드해서 전문을 읽는다. 사람이 실제로 확인한 경우에만 images_checked=true로 바꾼다.

검토자가 각자 사본에서 답 판단을 완료한 뒤 라벨을 고정한다. 그 다음 취합 담당자가 coordinator/gate18_answer_key.jsonl로 gate-on Judge와 gate-off 자동 규칙을 비교한다. 의견이 다르면 근거 원문으로 조정하며, 공식 gold와 같다는 이유로 사람 추출 라벨을 고치지 않는다. 이 18건의 일치율은 전체 900건 추출 정확도의 추정값이 아니다.
