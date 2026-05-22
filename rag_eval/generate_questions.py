from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from rag_eval.common import DEFAULT_MODES, ensure_output_dir, write_json


QUESTION_BANK: list[dict[str, Any]] = [
    {
        "question": "在达米尔港“飞鱼与酒”酒吧事件中，克莱恩最初想打听什么信息？请只回答当前事件内已经出现的事实。",
        "type": "fact",
        "expected_strength": "naive",
        "evaluation_focus": "单点事实命中与当前事件边界",
        "boundary_constraint": "限定在达米尔港酒吧事件，不引入后续章节。",
        "ideal_answer_criteria": ["指出克莱恩来酒吧主要是搜集最近传闻/情报", "说明回答依据来自艾尔兰、酒保或酒客场景", "不扩展到后续冒险"],
        "bad_answer_patterns": ["混入后续剧情", "把目的泛化为全部海上行动", "缺少当前事件证据"],
    },
    {
        "question": "“海雕”洛根在当前事件里真实扮演了什么角色？他和“地狱上将”路德维尔的关系是否已被证实？",
        "type": "fact",
        "expected_strength": "naive",
        "evaluation_focus": "事实核验与谣言/真相区分",
        "boundary_constraint": "只依据当前事件揭示的信息。",
        "ideal_answer_criteria": ["说明洛根借传闻吓人并参与讹诈", "指出路德维尔线人身份未被证实且被酒保否认", "区分传闻、自称和已证实事实"],
        "bad_answer_patterns": ["把洛根直接说成路德维尔线人", "忽略酒保的澄清", "引用后文信息"],
    },
    {
        "question": "伍迪拿出的“幽灵帝国”线索在骗局中起到了什么作用？",
        "type": "fact",
        "expected_strength": "naive",
        "evaluation_focus": "物品/信息诱饵的局部事实",
        "boundary_constraint": "限定“飞鱼与酒”酒吧骗局。",
        "ideal_answer_criteria": ["说明书信/线索用于诱导外乡人投资", "指出它服务于让洛根出场的骗局链条", "不把幽灵帝国当作已验证宝藏线索"],
        "bad_answer_patterns": ["把线索当真", "只复述宝藏传说", "跳到后续航海剧情"],
    },
    {
        "question": "艾尔兰船长在酒吧前后给了克莱恩哪些提醒？这些提醒如何影响读者对达米尔港环境的判断？",
        "type": "local_relation",
        "expected_strength": "local",
        "evaluation_focus": "人物提醒、地点风险与环境判断关系",
        "boundary_constraint": "限定艾尔兰与达米尔港酒吧场景。",
        "ideal_answer_criteria": ["列出不要找女人、不要相信这里任何人等提醒", "关联达米尔港骗局、谣言和海盗影响", "说明提醒与后续洛根骗局互相印证"],
        "bad_answer_patterns": ["只罗列提醒不解释关系", "泛化到所有海上城市", "混入后续章节"],
    },
    {
        "question": "在“飞鱼与酒”事件中，伍迪、洛根、酒保三者如何配合形成讹诈链条？",
        "type": "local_relation",
        "expected_strength": "local",
        "evaluation_focus": "局部实体关系与行动分工",
        "boundary_constraint": "只分析当前酒吧事件中的角色分工。",
        "ideal_answer_criteria": ["说明伍迪负责低级诱饵", "说明洛根借揭穿诱饵赢得信任再强买强卖", "说明酒保配合高价腌肉/收钱"],
        "bad_answer_patterns": ["遗漏任一关键参与者", "把三者关系说成偶然", "只讲克莱恩打人不讲骗局结构"],
    },
    {
        "question": "洛根为什么故意让克莱恩产生“他在帮忙揭穿伍迪”的误判？这个误判服务于什么计划？",
        "type": "causal_chain",
        "expected_strength": "hybrid",
        "evaluation_focus": "诱饵、误判、信任转移与讹诈因果链",
        "boundary_constraint": "限定当前骗局，不引用后续剧情。",
        "ideal_answer_criteria": ["解释先用伍迪制造容易识破的骗局", "解释洛根出场获得目标好感/降低戒心", "解释最终转向高价腌肉讹诈"],
        "bad_answer_patterns": ["只说洛根贪钱", "忽略误判机制", "把计划说成海盗组织安排"],
    },
    {
        "question": "克莱恩为什么选择用格尔曼·斯帕罗的人设直接反制洛根，而不是付钱离开？请串联人设、风险和行动结果。",
        "type": "causal_chain",
        "expected_strength": "hybrid",
        "evaluation_focus": "人物设定、策略选择、行动后果",
        "boundary_constraint": "只依据当前上下文和已出现的人设描述。",
        "ideal_answer_criteria": ["指出格尔曼人设是略疯狂的冒险家/赏金猎人", "解释直接暴力反制符合人设且能震慑", "说明结果揭穿洛根并迫使酒保讲传闻"],
        "bad_answer_patterns": ["忽略人设动机", "只写打斗过程", "引入后续已发生剧情"],
    },
    {
        "question": "当前事件里有哪些情报来源、传递方式、接收对象和用途？请按“来源—方式—对象—用途”组织。",
        "type": "global_relation",
        "expected_strength": "global",
        "evaluation_focus": "情报网络式关系组织",
        "boundary_constraint": "限定达米尔港酒吧及其相关传闻。",
        "ideal_answer_criteria": ["覆盖艾尔兰、伍迪/洛根、酒保、酒客传闻等来源", "区分谣言、骗局材料、直接讲述", "说明克莱恩如何筛选并利用信息"],
        "bad_answer_patterns": ["只列人物不讲传递方式", "把谣言当事实", "答案过宽泛"],
    },
    {
        "question": "只根据当前上下文，不引用后续章节，克莱恩离开酒吧后短期最可能围绕哪些目标行动？请区分短期行动和长期目标。",
        "type": "timeline_boundary",
        "expected_strength": "mix",
        "evaluation_focus": "时间线边界、计划/事实区分",
        "boundary_constraint": "不得引用后文已发生剧情，只能基于酒吧事件和离开时状态推断。",
        "ideal_answer_criteria": ["短期围绕摆脱追踪/确认安全/继续搜集情报", "长期围绕海上冒险、赏金或目标调查", "明确这是推断不是后续事实"],
        "bad_answer_patterns": ["混入后续剧情", "把推断写成已发生事实", "不区分短期和长期"],
    },
    {
        "question": "在当前剧情节点，克莱恩手里有哪些线索、资源、风险和下一步行动选项？请按“目标—人物—资源—风险—行动”回答。",
        "type": "state_reasoning",
        "expected_strength": "mix",
        "evaluation_focus": "当前状态关系链组织",
        "boundary_constraint": "只根据当前剧情节点，不使用上帝视角。",
        "ideal_answer_criteria": ["目标是搜集传闻/维持人设/规避麻烦", "人物包括艾尔兰、酒保、洛根、黑斗篷男子等当前相关者", "资源包括金币占卜、武器、人设、酒保提供的传闻", "风险包括白鲨、海盗关系、跟踪者"],
        "bad_answer_patterns": ["只罗列不形成目标链", "混入后续章节已知目标", "遗漏风险"],
    },
    {
        "question": "不要引入后续剧情：黑斗篷男子招揽克莱恩时提出了哪些利益和风险判断？这些判断是否都已被当前上下文证实？",
        "type": "anti_pollution",
        "expected_strength": "hybrid",
        "evaluation_focus": "反污染、已证实/未证实区分",
        "boundary_constraint": "只使用招揽出现时的上下文。",
        "ideal_answer_criteria": ["指出他认可克莱恩表现并提出加入", "指出他声称可处理白鲨麻烦", "区分白鲨与海盗有联系是其说法而非完全证实"],
        "bad_answer_patterns": ["引用黑斗篷男子后续身份", "把未证实说法当确定事实", "忽略风险判断"],
    },
    {
        "question": "“白鲨”汉密尔顿在当前事件链中为什么重要？请说明他与酒吧、酒保、洛根及潜在风险的关系。",
        "type": "local_relation",
        "expected_strength": "local",
        "evaluation_focus": "地点/组织化势力关系",
        "boundary_constraint": "限定当前事件及黑斗篷男子已经说出的内容。",
        "ideal_answer_criteria": ["说明白鲨是酒保口中的老板/酒吧背后势力", "说明克莱恩打了其酒吧的人会带来麻烦", "说明与海盗联系仍需标注信息来源"],
        "bad_answer_patterns": ["把白鲨关系过度展开", "忽略信息来源", "时间线越界"],
    },
    {
        "question": "当前事件中，“传闻”如何同时影响洛根的威慑力、酒客反应和克莱恩的判断？",
        "type": "causal_chain",
        "expected_strength": "hybrid",
        "evaluation_focus": "传闻驱动的多跳因果",
        "boundary_constraint": "限定洛根冒充线人这一事件。",
        "ideal_answer_criteria": ["说明洛根利用线人传闻制造恐惧", "说明酒客前期不敢起哄/后期吐唾沫的反转", "说明克莱恩从反常强调和套路中判断骗局"],
        "bad_answer_patterns": ["只写传闻内容", "忽略酒客反应变化", "把洛根身份判断错误"],
    },
    {
        "question": "达米尔港这一地点在当前章节里呈现出哪些势力和风险网络？请不要扩展到其他海域后续剧情。",
        "type": "global_relation",
        "expected_strength": "global",
        "evaluation_focus": "地点中心的势力网络",
        "boundary_constraint": "限定达米尔港和酒吧中被提到的势力。",
        "ideal_answer_criteria": ["覆盖海军、海盗传闻、白鲨、酒吧地头蛇、外来冒险者", "说明这些势力通过传闻/恐惧/利益连接", "不把其他章节势力混入"],
        "bad_answer_patterns": ["答案过宽", "混入其他地点势力", "只讲一个人物"],
    },
    {
        "question": "只看当前事件，克莱恩对“幽灵帝国”线索应持什么态度？为什么？",
        "type": "anti_pollution",
        "expected_strength": "naive",
        "evaluation_focus": "当前上下文限定与诱饵识别",
        "boundary_constraint": "不得引用幽灵帝国后续是否真实出现。",
        "ideal_answer_criteria": ["应保持怀疑", "依据是伍迪外乡人骗局、资料未被验证、洛根配合", "明确不能判定后续真伪"],
        "bad_answer_patterns": ["提前剧透后续真相", "把线索当确定事实", "忽略骗局语境"],
    },
    {
        "question": "克莱恩在处理酒保时为什么先正常付款、吃腌肉，之后仍给酒保教训？请解释这个行动链的目的。",
        "type": "causal_chain",
        "expected_strength": "hybrid",
        "evaluation_focus": "行动顺序与策略目的",
        "boundary_constraint": "限定酒吧事件内的行为。",
        "ideal_answer_criteria": ["说明正常付款维持可控局面/避免单纯抢劫", "说明惩戒酒保针对其配合讹诈", "说明行动服务于格尔曼人设和震慑"],
        "bad_answer_patterns": ["只说性格暴力", "忽略付款与惩戒的顺序意义", "时间线污染"],
    },
    {
        "question": "当前章节中哪些人对洛根的判断发生变化？分别基于什么证据？",
        "type": "local_relation",
        "expected_strength": "local",
        "evaluation_focus": "范围限定型评价变化",
        "boundary_constraint": "限定“洛根被揭穿”前后，不引用后续章节评价。",
        "ideal_answer_criteria": ["酒客从害怕到唾弃", "酒保从配合到否认其线人身份", "克莱恩从怀疑到确认讹诈套路", "每个变化附证据"],
        "bad_answer_patterns": ["召回同一人物后续所有评价", "只说结果不说证据", "实体关系错误"],
    },
    {
        "question": "在当前上下文中，金币占卜这一资源如何影响克莱恩离开酒吧后的安全判断？",
        "type": "fact",
        "expected_strength": "naive",
        "evaluation_focus": "物品/能力与行动关系的事实识别",
        "boundary_constraint": "只回答离开酒吧后立即发生的场景。",
        "ideal_answer_criteria": ["说明金币在指间跳跃用于侦察/占卜判断", "关联克莱恩改变路线或确认跟踪", "不扩展到金币的完整能力体系"],
        "bad_answer_patterns": ["泛讲占卜体系", "混入后续能力升级", "遗漏当前行动"],
    },
    {
        "question": "请比较“海军指控洛根”和“酒保揭穿洛根”两段信息：哪一段更能作为当前事实依据？为什么？",
        "type": "state_reasoning",
        "expected_strength": "mix",
        "evaluation_focus": "证据强弱与事实边界",
        "boundary_constraint": "只比较当前事件内的信息来源。",
        "ideal_answer_criteria": ["海军指控属于传闻/被安排可能", "酒保揭穿发生在洛根被制服后且解释了套路", "仍需承认酒保也可能自保但更贴合当前证据链"],
        "bad_answer_patterns": ["把两者同等当真", "忽略海军可能被雇佣", "过度确定"],
    },
    {
        "question": "当前酒吧事件能体现格尔曼·斯帕罗人设的哪些特征？请结合具体行为，不要泛泛评价。",
        "type": "fact",
        "expected_strength": "naive",
        "evaluation_focus": "细节事实与人物设定",
        "boundary_constraint": "限定当前事件里的行为证据。",
        "ideal_answer_criteria": ["冷静、危险、略显疯狂、强硬", "结合反问、动手、拔枪、震慑酒保等行为", "不引入后续名声"],
        "bad_answer_patterns": ["只给形容词", "引用后续名场面", "缺少行为证据"],
    },
    {
        "question": "从当前章节看，达米尔港酒吧里的“信息”有哪些污染源？克莱恩如何降低被污染信息误导的风险？",
        "type": "anti_pollution",
        "expected_strength": "hybrid",
        "evaluation_focus": "检索污染类比与信息可靠性",
        "boundary_constraint": "限定当前章节，不引入其他章节情报。",
        "ideal_answer_criteria": ["污染源包括酒客吹牛、伍迪假资料、洛根自造传闻、酒保配合", "克莱恩通过观察、怀疑、反制和追问筛选", "区分可用传闻与未证实传闻"],
        "bad_answer_patterns": ["把全部信息都视为真", "不讲污染源", "答案过宽"],
    },
    {
        "question": "如果只根据当前上下文，黑斗篷男子的招揽可能给克莱恩带来哪些短期机会和风险？",
        "type": "timeline_boundary",
        "expected_strength": "mix",
        "evaluation_focus": "后续计划型时间线控制",
        "boundary_constraint": "不要说明黑斗篷男子后续真实身份或后续剧情。",
        "ideal_answer_criteria": ["机会包括解决白鲨麻烦、加入某组织/获得情报", "风险包括身份不明、动机不明、可能卷入海盗势力", "明确为当前推断"],
        "bad_answer_patterns": ["直接剧透身份", "把后续事件提前当事实", "不区分机会和风险"],
    },
    {
        "question": "围绕“白鲨—酒吧—海盗传闻—外来冒险者”，当前章节形成了怎样的关系网络？",
        "type": "global_relation",
        "expected_strength": "global",
        "evaluation_focus": "多实体关系网络",
        "boundary_constraint": "只使用当前章节已经出现或被陈述的信息。",
        "ideal_answer_criteria": ["白鲨作为酒吧背后老板和潜在海盗关联点", "酒吧是信息和骗局发生场", "外来冒险者成为被试探/讹诈对象", "标注传闻与事实差异"],
        "bad_answer_patterns": ["不区分传闻和事实", "漏掉外来冒险者视角", "关系链断裂"],
    },
    {
        "question": "“特制腌肉”这件物品如何影响当前事件中的人物判断、行动和风险？",
        "type": "local_relation",
        "expected_strength": "local",
        "evaluation_focus": "物品影响链",
        "boundary_constraint": "限定酒吧讹诈事件。",
        "ideal_answer_criteria": ["腌肉是强买强卖的载体", "触发克莱恩识别骗局并反制", "引出酒保/洛根/守卫/白鲨风险"],
        "bad_answer_patterns": ["只描述食物味道", "忽略讹诈功能", "扩展到无关物品"],
    },
    {
        "question": "当前事件中，哪些内容属于“已经发生的事”，哪些属于“当前计划/声称的事”，哪些只能算“后续可能发生的风险”？",
        "type": "state_reasoning",
        "expected_strength": "mix",
        "evaluation_focus": "事实、计划、风险三分法",
        "boundary_constraint": "只依据当前章节，不使用后续剧情。",
        "ideal_answer_criteria": ["已发生：酒吧冲突、骗局、反制、离开、遭跟踪", "当前计划/声称：伍迪筹钱、黑斗篷招揽/解决麻烦", "风险：白鲨报复、海盗联系、跟踪者动机"],
        "bad_answer_patterns": ["把风险写成已发生", "把骗局声称当事实", "混入后文"],
    },
    {
        "question": "在当前章节中，海军、海盗、地头蛇、冒险者之间的关系是如何通过传闻和恐惧被连接起来的？",
        "type": "global_relation",
        "expected_strength": "global",
        "evaluation_focus": "组织/身份网络与传播机制",
        "boundary_constraint": "限定达米尔港酒吧及相关传闻。",
        "ideal_answer_criteria": ["海军指控/被雇佣制造线人传闻", "海盗名号提供威慑", "地头蛇用恐惧牟利", "冒险者需要判断真假并承担风险"],
        "bad_answer_patterns": ["把关系说成正式组织结构", "遗漏传闻机制", "过度概括"],
    },
    {
        "question": "只根据当前上下文，克莱恩为什么没有完全相信任何一方的话？请列出至少三类不可靠信号。",
        "type": "anti_pollution",
        "expected_strength": "hybrid",
        "evaluation_focus": "当前上下文约束与信息可靠性",
        "boundary_constraint": "不得引用后文验证结果。",
        "ideal_answer_criteria": ["艾尔兰提醒不要相信任何人", "伍迪资料像骗局", "洛根过度强调清白且套路反常", "酒保与洛根配合"],
        "bad_answer_patterns": ["引用后文证明", "只说克莱恩聪明", "缺少不可靠信号"],
    },
    {
        "question": "如果把当前事件抽象成“目标—人物—资源—风险—行动”链，克莱恩的最优短期策略是什么？",
        "type": "state_reasoning",
        "expected_strength": "mix",
        "evaluation_focus": "当前状态推理与行动链",
        "boundary_constraint": "只做当前节点推理，不说明后续实际发展。",
        "ideal_answer_criteria": ["目标：获取可靠情报并保持人设", "资源：武力、占卜、观察、已获得传闻", "风险：白鲨/跟踪者/谣言污染", "行动：脱离现场、确认跟踪、谨慎接触招揽者"],
        "bad_answer_patterns": ["写成后续剧情复述", "缺少资源或风险", "过度乐观"],
    },
    {
        "question": "当前章节中，为什么“答案很丰富”反而可能是错误的？请以达米尔港事件为例说明哪些扩展会越界。",
        "type": "timeline_boundary",
        "expected_strength": "mix",
        "evaluation_focus": "边界控制与过度召回识别",
        "boundary_constraint": "只讨论当前事件能支持的内容。",
        "ideal_answer_criteria": ["指出后续身份、后续航线、后续组织内幕都可能越界", "说明当前可支持的是酒吧骗局、传闻、招揽和风险", "强调丰富但无依据会降低可信度"],
        "bad_answer_patterns": ["为了丰富而剧透", "不指出当前证据范围", "把后续事实当解释"],
    },
    {
        "question": "在“洛根被揭穿”这一局部事件中，哪些关系是 Graph-RAG 应该比 naive 更容易组织清楚的？",
        "type": "local_relation",
        "expected_strength": "local",
        "evaluation_focus": "Graph-RAG 关系链优势观察",
        "boundary_constraint": "限定局部事件，不泛化到整本书。",
        "ideal_answer_criteria": ["伍迪—洛根—酒保的协作/利益链", "洛根—路德维尔传闻的真伪关系", "克莱恩—洛根的反制关系", "酒吧—白鲨的风险关系"],
        "bad_answer_patterns": ["只说 naive/Graph-RAG 概念", "不回到事件实体", "混入无关章节"],
    },
    {
        "question": "请只根据当前事件回答：克莱恩已经确认了什么？尚未确认什么？下一步需要验证什么？",
        "type": "anti_pollution",
        "expected_strength": "mix",
        "evaluation_focus": "已知/未知/待验证边界",
        "boundary_constraint": "不得引用后续章节或读者上帝视角。",
        "ideal_answer_criteria": ["已确认酒吧存在讹诈套路、洛根线人身份可疑/被否认、有人跟踪", "尚未确认白鲨具体反应、黑斗篷男子身份和动机", "待验证招揽可信度、跟踪者目的、海盗关系真实性"],
        "bad_answer_patterns": ["把未确认内容写成事实", "剧透跟踪者身份", "遗漏待验证项"],
    },
    {
        "question": "从第499章到第500章开头，事件链如何从“酒吧骗局”转入“被招揽”？请按时间顺序说明因果节点。",
        "type": "causal_chain",
        "expected_strength": "hybrid",
        "evaluation_focus": "跨章节事件链和因果链",
        "boundary_constraint": "只覆盖第499章到第500章开头已经出现的内容。",
        "ideal_answer_criteria": ["酒吧搜集情报", "遭遇骗局并暴力反制", "得罪白鲨势力", "离开后用金币确认异常/跟踪", "黑斗篷男子因欣赏其表现并以解决麻烦招揽"],
        "bad_answer_patterns": ["跳过关键节点", "只罗列不解释因果", "继续讲后续章节"],
    },
]


def _with_common_fields(index: int, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"Q{index:03d}",
        "question": item["question"],
        "type": item["type"],
        "target_modes": list(DEFAULT_MODES),
        "expected_strength": item["expected_strength"],
        "evaluation_focus": item["evaluation_focus"],
        "boundary_constraint": item["boundary_constraint"],
        "ideal_answer_criteria": item["ideal_answer_criteria"],
        "bad_answer_patterns": item["bad_answer_patterns"],
    }


def generate_questions(num_questions: int = 30, document_name: str = "") -> list[dict[str, Any]]:
    if num_questions < 1:
        raise ValueError("num_questions must be >= 1")
    selected = [QUESTION_BANK[index % len(QUESTION_BANK)] for index in range(num_questions)]
    questions = [_with_common_fields(index, item) for index, item in enumerate(selected, start=1)]
    if document_name:
        for item in questions:
            item["document_hint"] = document_name
    return questions


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate LightRAG mode-comparison questions.")
    parser.add_argument("--num-questions", type=int, default=30)
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--source-doc", default="诡秘之主(501-1000章).txt")
    args = parser.parse_args()

    output_dir = ensure_output_dir(args.output_dir)
    questions = generate_questions(args.num_questions, Path(args.source_doc).name)
    write_json(output_dir / "questions.json", questions)
    print(f"Wrote {len(questions)} questions to {output_dir / 'questions.json'}")


if __name__ == "__main__":
    main()
