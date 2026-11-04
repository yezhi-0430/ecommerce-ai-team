"""保守的文本提示，不替代人工审核或图片核验。"""
import re

NUMBER = re.compile(r'(?<![\d.])(\d+(?:\.\d+)?)\s*(毫升|ml|mL|ML|元|小时|分钟|天|千克|公斤|kg|克|g)(?![a-zA-Z])')
CLAIMS = ('防漏', '不漏水', '无毒', '食品级', '长效保温', '长效保冷', '抗菌', '认证', '安全无害', '七天无理由', '7天无理由', '检测报告', '计量标准', '哑光', '抗指纹', '耐刮', '防刮', '便携', '轻便')
NEGATION = ('未知', '未提供', '未确认', '不确定', '无法确认', '无法核实', '暂无', '未说明', '不能确认', '禁止', '不可', '不应', '未经')

def check_claims(text: str, product=None) -> list[str]:
    findings = []
    for clause in re.split(r'[，,。！？!？\n；;]|但是|然而|但', text):
        if any(marker in clause for marker in NEGATION):
            continue
        for match in NUMBER.finditer(clause):
            number, unit = match.groups()
            if (product is None and ((number == '500' and unit.lower() in ('ml','毫升')) or (number == '79' and unit == '元'))) or (product is not None and any(m.group(1) == number and m.group(2).lower() == unit.lower() for m in NUMBER.finditer(' '.join(str(v) for k, v in product.items() if k != '未知信息')))):
                continue
            finding = f'待核实参数：{match.group(0)}（不在已知商品资料中）'
            if finding not in findings: findings.append(finding)
        for match in re.finditer(r"(?<!\d)(?:304|316|201|18/8|18/10)\s*(?:不锈钢|stainless\s*steel)", clause, re.IGNORECASE):
            finding = f'待核实材质等级：{match.group(0)}（资料只确认不锈钢）'
            if finding not in findings: findings.append(finding)
        for match in re.finditer(r"(?<![a-zA-Z0-9])GB(?:/T)?\s*\d+(?:[.\-]\d+)*", clause, re.IGNORECASE):
            finding = f'待核实标准编号：{match.group(0)}（资料未提供）'
            if finding not in findings: findings.append(finding)
        for claim in CLAIMS:
            if claim in clause:
                finding = f'待核实表述：{claim}（资料未确认相关功效或认证）'
                if finding not in findings: findings.append(finding)
    return findings

DESIGN_PATTERNS = (r'旋盖', r'旋转.{0,4}(?:杯盖|开盖|开合)', r'(?:杯盖|开盖).{0,4}旋转', r'螺纹', r'密封圈', r'单手.{0,4}(?:开盖|开合)', r'PANTONE\s*[0-9][0-9A-Z-]*', r'(?<!\d)\d+(?:\.\d+)?\s*秒')

def risky_design_claims(text: str) -> list[str]:
    findings = []
    for clause in re.split(r'[，,。！？!？\n；;]|但是|然而|但', text):
        if any(marker in clause for marker in NEGATION):
            continue
        for pattern in DESIGN_PATTERNS:
            for match in re.finditer(pattern, clause, re.IGNORECASE):
                if match.group(0) not in findings:
                    findings.append(match.group(0))
    return findings
