from app.quality import check_claims

def test_detects_unset_duration_and_feature():
    findings = check_claims('容量500ml，保温24小时，绝对防漏')
    assert any('24小时' in item for item in findings)
    assert any('防漏' in item for item in findings)
    assert not any('500ml' in item for item in findings)

def test_known_product_numbers_are_accepted():
    assert check_claims('容量500ml，售价79元。') == []

def test_disclaimed_unknowns_are_not_treated_as_claims():
    assert not any('防漏' in x for x in check_claims('是否防漏：暂无资料'))
from app.quality import risky_design_claims

def test_blocks_invented_product_design():
    findings = risky_design_claims('商品事实：旋盖式杯盖，PANTONE 19-3926，0.5秒单手开盖，带密封圈。')
    assert any('旋盖' in x for x in findings)
    assert any('PANTONE' in x for x in findings)
    assert any('0.5秒' in x for x in findings)

def test_unknown_design_can_be_marked_unverified():
    assert risky_design_claims('未知是否旋盖。未确认密封圈。') == []

def test_mentioning_color_tool_is_not_a_claimed_code():
    assert risky_design_claims('可以使用 Pantone色值对比工具作为参考。') == []

def test_unconfirmed_steel_grade_is_flagged():
    assert any('304不锈钢' in item for item in check_claims('雾蓝水杯，304不锈钢'))

def test_unsupported_policies_and_certification_are_flagged():
    found=check_claims('提供七天无理由退换，符合GB4806.9-2016国标及计量标准，附检测报告。')
    assert any('七天无理由' in x for x in found)
    assert any('GB4806.9-2016' in x for x in found)
    assert any('检测报告' in x for x in found)
from app.quality import risky_design_claims, check_claims

def test_unsupported_material_and_standard_in_lead_are_detected():
    text='商品卖点：食品接触用304不锈钢（GB4806.9-2016）。'
    findings=check_claims(text) + risky_design_claims(text)
    assert any('304' in x for x in findings)
    assert any('GB4806' in x for x in findings)

def test_unknown_surface_and_portability_are_flagged():
    result=check_claims('雾蓝色哑光杯身，方便携带且抗指纹。')
    assert any('哑光' in x for x in result)
    assert any('抗指纹' in x for x in result)

def test_unknown_fact_does_not_hide_an_unrelated_assertion():
    assert any('防漏' in x for x in check_claims('重量未知，但绝对防漏。'))
    assert risky_design_claims('重量未知，但采用旋盖。')

def test_unknown_product_information_does_not_authorize_numbers():
    assert check_claims('保温24小时', {'名称':'杯子', '未知信息':'保温24小时是否属实未知'})

def test_unknown_fact_followed_by_comma_does_not_hide_claim():
    assert any('抗菌' in x for x in check_claims('材质未知，具有抗菌功能。'))
    assert risky_design_claims('重量未知，采用旋盖。')
