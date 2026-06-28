"""
Translate Chinese questions to English search queries for cross-lingual retrieval.
Also extracts key concepts for knowledge graph lookup.

策略(2026-06 更新):
1. 进入 LLM 前先用领域术语词典把生僻焦化中文术语替换为标准英文术语
   (避免 qwen3:8b 把"捣固焦"翻成"Solidified coke"这种语义飘移)
2. 把"术语预替换后的版本"作为 english_queries[0] 兜底,保证即使 LLM 翻车
   也至少有一个术语正确的候选
3. LLM 再生成 1-2 个 paraphrase 候选,丰富 dense 检索多样性
"""
import json
import re

from ..llm_client import chat_json


# ─── 焦化领域 中→英 术语词典(防 LLM 翻错) ──────────────────────
# 元组列表(不是 dict)以保证按 key 长度降序匹配,避免短 key 吃掉长 key
# 例如先匹配"捣固焦炉"再匹配"捣固焦",先匹配"焦炭反应后强度"再匹配"反应后强度"
_CN2EN_TERMS_RAW = [
    ("焦化工艺", "coking process"),
    ("焦化", "coking / carbonization"),
    ("煤的炭化", "coal carbonization"),
    ("炭化", "carbonisation"),
    ("煤化", "coalification"),
    ("热解", "pyrolysis"),
    ("共热解", "co-pyrolysis"),
    ("快速热解", "fast pyrolysis"),
    ("脱挥发分", "devolatilisation"),
    ("煤的脱挥发分", "coal devolatilisation"),
    ("挥发分释出", "volatile matter release"),
    ("挥发分释放动力学", "volatile release kinetics"),
    ("脱羧反应", "carboxylic group decarboxylation"),
    ("脱烷基反应", "dealkylation"),
    ("缩合反应", "ring condensation reaction"),
    ("芳环缩合", "aromatic ring condensation"),
    ("芳烃缩合", "aromatic condensation"),
    ("芳环融合", "aromatic ring fusion"),
    ("芳环聚合", "aromatic ring polymerization"),
    ("成环反应", "ring closure reaction"),
    ("聚合反应", "polymerisation reaction"),
    ("再聚合", "repolymerisation"),
    ("再聚合反应", "re-polymerisation"),
    ("再聚合动力学", "repolymerization kinetics"),
    ("热聚合反应", "thermal polymerization"),
    ("键的断裂", "bond cleavage"),
    ("键断裂", "bond scission"),
    ("桥键断裂", "bridge-bond cleavage"),
    ("桥键破裂", "bridge-bond rupture"),
    ("脂肪族结构键断裂", "bond cleavage of aliphatic structures"),
    ("侧链脱除", "side-chain elimination"),
    ("侧链断裂", "side chain cleavage"),
    ("侧链剪断", "side chain scission"),
    ("侧链脱附", "side-chain detachment"),
    ("交联反应", "cross-linking reactions"),
    ("分子重排", "molecular rearrangements"),
    ("熔融镜质组的分子重排", "molecular rearrangements of fused vitrinite"),
    ("可转移氢自由基", "transferable hydrogen radicals"),
    ("可转移自由基", "transferable radicals"),
    ("自由基稳定化", "radical stabilization"),
    ("逆向反应", "retrogressive reaction"),
    ("焦油气化", "tar vaporisation"),
    ("焦油生成", "tar generation"),
    ("焦油缩合", "tar condensation"),
    ("脱硫", "desulfurization"),
    ("焦煤", "metallurgical coal"),
    ("炼焦煤", "coking coal / metallurgical coal"),
    ("优质焦煤", "premium coking coal"),
    ("配煤", "coal blending / blend formulation"),
    ("配合煤", "coal blend"),
    ("配煤组成", "coal blend composition"),
    ("三元配煤", "ternary coal blends"),
    ("煤阶", "coal rank"),
    ("煤阶分类", "coal rank classification"),
    ("烟煤", "bituminous rank"),
    ("次烟煤", "subbituminous coal"),
    ("澳洲炼焦煤", "Australian coking coals"),
    ("煤岩组分", "coal macerals"),
    ("煤岩组分组成", "maceral composition"),
    ("煤岩组成", "coal maceral composition"),
    ("镜质组", "vitrinite"),
    ("镜质组含量", "vitrinite content"),
    ("镜质组最大反射率", "mean maximum vitrinite reflectance"),
    ("镜质组反射率", "reflectance of vitrinite (Ro)"),
    ("平均最大镜质组反射率", "mean max vitrinite reflectance (MMVR)"),
    ("熔融镜质组", "fused vitrinite"),
    ("富氢镜质组", "perhydrous vitrinite"),
    ("镜质组富集煤", "vitrinite-rich coal"),
    ("惰质组", "inertinite"),
    ("惰质组组分", "inertinite macerals"),
    ("惰质组富集煤", "inertinite-rich coal"),
    ("未熔惰质组", "unfused inertinite"),
    ("惰质组热稳定性", "inertinite thermal stability"),
    ("壳质组", "liptinite (exinite)"),
    ("活性组分", "reactive maceral"),
    ("矿物质", "mineral matter"),
    ("工业分析", "proximate analysis"),
    ("元素分析", "ultimate analysis"),
    ("煤岩分析", "petrographic analysis"),
    ("内在水分", "inherent moisture (IM)"),
    ("挥发分", "volatile matter (VM)"),
    ("固定碳", "fixed carbon (FC)"),
    ("灰分", "ash content"),
    ("全水分", "total moisture"),
    ("粘结性", "caking property"),
    ("黏结性", "caking property"),
    ("流变性", "rheological property / Gieseler plasticity"),
    ("流变特性", "rheological properties"),
    ("吉斯勒流动度", "Gieseler fluidity"),
    ("最大流动度", "maximum Gieseler fluidity"),
    ("吉斯勒最大流动度", "maximum Gieseler fluidity"),
    ("吉斯勒特征温度", "Gieseler characteristic temperatures"),
    ("热塑性", "thermoplasticity"),
    ("热塑性区间", "thermoplastic range"),
    ("煤的热塑性", "thermoplasticities of coals"),
    ("软化温度", "softening temperature"),
    ("初始软化温度", "initial softening temperature (IST)"),
    ("固化温度", "resolidification temperature"),
    ("再固化温度", "resolidification temperature"),
    ("固化温度2", "solidification temperature (ST)"),
    ("总膨胀度", "total dilatation"),
    ("膨胀指数", "swell index"),
    ("膨胀指数试验", "swelling index test"),
    ("煤膨胀比", "coal swelling ratio"),
    ("煤的膨胀行为", "coal swelling behavior"),
    ("膨胀压力", "Swelling pressure"),
    ("等容膨胀", "isometric expansion"),
    ("软化-熔融阶段", "softening-melting stage"),
    ("软化热塑性区间", "softening thermoplastic intervals"),
    ("延迟软化点", "delayed softening point"),
    ("煤的塑性性质", "coal plastic properties"),
    ("配煤对热塑性区间的影响", "coal blending effects on thermoplastic range"),
    ("最低粘度", "minimum viscosity"),
    ("分子量分布", "molecular weight distribution"),
    ("胶质层", "plastic layer"),
    ("胶质层阶段", "plastic layer stage"),
    ("胶质层厚度", "thickness of the plastic layer"),
    ("胶质区", "plastic range"),
    ("初始软化层", "initial softening layer"),
    ("中间胶质层", "intermediate plastic layer"),
    ("接近再固化层", "near-resolidified layer"),
    ("内聚塑性体", "cohesive plastic mass"),
    ("胶质体", "metaplast"),
    ("胶质体形成", "metaplast formation"),
    ("半焦/胶质层", "semi-coke and plastic layers"),
    ("均质流体相", "homogeneous fluid phase"),
    ("液晶相", "liquid crystalline phase"),
    ("中间相", "mesophase formation"),
    ("β-树脂阶段", "beta resin stage"),
    ("非挥发性流体产物", "fluid non-volatile product"),
    ("泡沫状热塑性物质", "foam-like thermoplastic material"),
    ("热塑性流动", "thermoplastic flow"),
    ("热塑性物质形成", "thermoplastic mass formation"),
    ("基质膨胀协同效应", "matrix swelling synergy"),
    ("溶剂膨胀效应", "solvent swelling effect"),
    ("可萃取物质", "extractable substances"),
    ("聚合物前驱体", "polymeric precursor"),
    ("供氢能力", "hydrogen donor capacity"),
    ("挤出物形成", "extrudate formation"),
    ("焦油残留物", "tarry residue"),
    ("半焦", "semi-coke / char"),
    ("半焦区域", "semi-coke region"),
    ("半焦粉", "semi-coke powders"),
    ("低渗透性半焦区", "low permeability semi-coke zone"),
    ("粘弹性半焦", "viscoelastic semi-coke"),
    ("半焦结构", "char structure"),
    ("半焦基质", "char matrix"),
    ("半焦残留物", "charring residue"),
    ("焦/半焦过渡", "coke/semi-coke transition"),
    ("焦炭", "metallurgical coke"),
    ("焦炭基质", "coke matrix"),
    ("焦炭微观结构", "coke microstructure"),
    ("焦炭结构有序化", "ordered coke structures"),
    ("无定形碳基体", "amorphous carbon matrix"),
    ("各向异性镶嵌结构", "anisotropic mosaic"),
    ("微观纹理发育", "microtexture development"),
    ("碳堆叠", "carbon stacking"),
    ("石墨烯状结构", "graphene-like structure"),
    ("纳米石墨层", "nanoscale graphitic layer"),
    ("石墨化", "graphitisation"),
    ("碳结构演化", "carbon structure evolution"),
    ("凝聚环系", "condensed ring system"),
    ("缩合芳环", "condensed aromatic rings"),
    ("稠合芳环", "fused aromatic ring"),
    ("芳团簇尺寸", "aromatic cluster size"),
    ("芳团簇尺寸演化", "aromatic cluster size evolution"),
    ("芳团簇发育", "aromatic cluster development"),
    ("簇内总芳碳", "total aromatic carbons per cluster (ωta)"),
    ("簇内质子化芳碳", "protonated aromatic carbons per cluster (ωp)"),
    ("簇内碳取代芳碳", "carbon-bonded aromatic carbons per cluster (ωc)"),
    ("骨架芳碳分率", "fraction of aromatic carbon in skeletal structures (far)"),
    ("芳碳分率", "fraction of aromatic carbons"),
    ("质子化芳碳", "protonated aromatic carbons"),
    ("碳取代芳碳", "carbon-bonded aromatic carbons"),
    ("芳香碳", "aromatic carbons"),
    ("芳香结构", "aromatic structures"),
    ("脂肪族结构", "aliphatic structures"),
    ("氢化芳烃结构", "hydroaromatic structures"),
    ("芳香度", "aromaticity"),
    ("反应性大分子结构", "reactive macromolecular structures"),
    ("物理化学结构", "physicochemical structures"),
    ("桥键", "bridge bonds"),
    ("桥键与环状结构", "bridge bonds and looped structures"),
    ("环状结构", "looped structures"),
    ("交联结构", "cross-linking structures"),
    ("更强交联结构", "stronger cross-linking structures"),
    ("侧链", "side chains"),
    ("烷基侧链", "alkyl side chains"),
    ("亚甲基碳", "methylene carbons"),
    ("芳/脂亚甲基碳", "methylene carbons (aromatic-bonded / aliphatic-bonded)"),
    ("甲基碳", "methyl carbons"),
    ("芳/脂甲基碳", "methyl carbons (aromatic-bonded / aliphatic-bonded)"),
    ("氧官能团", "oxygen functional groups"),
    ("酚类化合物", "phenolic compounds"),
    ("多环芳烃", "polycyclic aromatic hydrocarbons (PAHs)"),
    ("簇内桥键与环数", "δb+l (bridges and loops per cluster)"),
    ("簇内侧链数", "σ0 (side chains per cluster)"),
    ("ACH2/ACH3 比", "ACH2/ACH3 ratio"),
    ("Aar-H/Aal-H 比", "Aar-H/Aal-H ratio"),
    ("孔隙率", "porosity"),
    ("孔体积分数", "void fraction (porosity)"),
    ("空隙分数", "void fraction (F)"),
    ("大孔", "macropore"),
    ("大孔群", "macropores"),
    ("大孔率", "macroporosity"),
    ("大孔数量", "number of macropores"),
    ("大孔演化阶段", "macropore evolution stages"),
    ("微孔", "microporosity"),
    ("中孔结构", "mesopore structure"),
    ("微孔闭合", "micropore closure"),
    ("闭孔", "closed pore"),
    ("开孔", "open pore"),
    ("孤立孔", "isolated pore"),
    ("孔径分布", "pore size distribution"),
    ("孔径分布(PSD)", "pore size distribution (PSD)"),
    ("大直径孔", "large-diameter voids"),
    ("平均孔径", "mean diameter (Md)"),
    ("3D 结构参数", "3D structural parameters"),
    ("3D 结构参数集", "3D structural parameters (Ft, Dn, Vf49.25μm, Mdmax)"),
    ("孔连通性", "pore connectivity"),
    ("孔网络连通性", "pore network connectivity"),
    ("开放孔网络", "open pore network"),
    ("孔成核", "pore nucleation"),
    ("孔成核与生长", "pore nucleation and growth"),
    ("气泡成核", "bubble nucleation"),
    ("气泡生长与聚并", "bubble growth and coalescence"),
    ("气泡生长机理", "bubble growth mechanism"),
    ("孔聚并", "pore coalescence"),
    ("孔结构聚并", "coalescence of pore structures"),
    ("聚并孔结构", "coalesced pore structure"),
    ("通道状孔", "channel-like pores"),
    ("晶粒内/晶粒间孔", "intragranular and intergranular pores"),
    ("镜质组渗入填充机理", "filling mechanism (vitrinite infiltration)"),
    ("孔演化", "porosity evolution"),
    ("挥发分滞留", "volatile matters entrapment"),
    ("孔内捕获气体", "gas trapped inside pores"),
    ("渗透演化", "permeability evolution"),
    ("气体渗透性", "gas permeability"),
    ("胶质区不透气边界", "impermeable boundary surrounding the plastic region"),
    ("气体扩散路径", "gas diffusion pathways"),
    ("渗流路径", "percolation pathways"),
    ("孔网络分形维数", "porous network fractal dimension"),
    ("孔分形几何", "pore fractal geometry"),
    ("孔分析中的滞回环", "hysteresis loop in pore analysis"),
    ("剥落现象", "spalling phenomenon"),
    ("超声检测焦炭", "ultrasonic testing of coke"),
    ("内部气压", "internal gas pressure (IGP)"),
    ("内部气压建立", "internal gas pressure build-up"),
    ("最大内部气压", "maximum internal gas pressure (IGP)"),
    ("内部气压原位测量", "in-situ measurements of IGP"),
    ("焦炉墙压力", "oven wall pressure (OWP)"),
    ("OWP", "OWP (oven wall pressure)"),
    ("最大气体释放速率", "maximum gas evolution rate"),
    ("压力驱动膨胀", "pressure-driven expansion"),
    ("压力驱动蒸气释放", "pressure-driven vapor release"),
    ("氢分压", "partial pressure of hydrogen"),
    ("分压梯度", "partial pressure gradient"),
    ("内嵌压力探头", "embedded pressure probes"),
    ("捣固焦炉", "tamping/stamp-charged coke oven (non-recovery)"),
    ("捣固焦", "tamping coke / non-recovery coke / stamped coke"),
    ("捣固炼焦", "stamp charging coking"),
    ("堆装焦炉", "top-charging coke oven"),
    ("堆装焦", "top-charging coke / conventional coke"),
    ("热回收焦炉", "heat-recovery coke oven"),
    ("副产品回收焦炉", "by-product recovery coke oven"),
    ("干熄焦", "CDQ (coke dry quenching)"),
    ("湿熄焦", "wet quenching"),
    ("熄焦塔", "quenching tower"),
    ("焦炉", "coke oven"),
    ("焦炉群", "coke oven battery"),
    ("可动壁焦炉", "movable-wall coke oven"),
    ("双壁加热焦炉", "dual-wall-heated coke oven"),
    ("双壁加热焦炉2", "double-wall-heated coke oven"),
    ("感应加热焦炉", "induction heating coke oven"),
    ("窄炭化室", "narrow coke chamber"),
    ("4kg 实验室焦炉装置", "4 kg laboratory-scale coke oven rig"),
    ("中试焦炉(CSIRO 400kg)", "pilot-scale coke ovens (400 kg at CSIRO)"),
    ("炼焦干馏罐", "coking retort"),
    ("焦炭反应器", "coke reactor"),
    ("石英管", "quartz tube"),
    ("绝缘砖", "insulation brick"),
    ("氧化铝板", "alumina boards"),
    ("碳化硅加热元件", "silicon carbide (SiC) heating element"),
    ("可编程温控系统", "programmable temperature control system"),
    ("热电偶", "thermocouple"),
    ("压力传感器", "pressure sensor"),
    ("取样探头", "sampling probe"),
    ("焦炉煤气", "coke oven gas (COG)"),
    ("焦油", "coal tar"),
    ("立火道", "flue / heating wall"),
    ("炭化室", "carbonization chamber / coke oven chamber"),
    ("上升管", "ascension pipe"),
    ("装煤车", "charging car"),
    ("推焦车", "pusher car"),
    ("装炉密度", "charging density"),
    ("堆密度", "bulk density"),
    ("堆密度控制", "bulk density control"),
    ("干法装炉", "dry coal charging process"),
    ("预热炉", "preheated oven"),
    ("快速冷却", "fast quenching"),
    ("氮气流", "nitrogen flow"),
    ("一维传热", "one-dimensional heat transfer"),
    ("一维传热梯度", "one-dimensional heat transfer gradient"),
    ("等温面", "isothermal planes"),
    ("温度梯度", "temperature gradient"),
    ("传热梯度", "heat transfer gradient"),
    ("温度分布", "temperature profiles"),
    ("温度平台(水分蒸发)", "temperature plateau (moisture evaporation)"),
    ("水分向中心迁移", "moisture migration to centre"),
    ("煤焦中心", "centre of the coal charge"),
    ("焦炉煤气侧", "coke side"),
    ("边界层现象", "boundary layer phenomena"),
    ("逐步脱挥发分", "progressive devolatilization"),
    ("由实测温度外推", "extrapolation from measured temperature profiles"),
    ("原位测量", "in-situ measurement"),
    ("原位 ESR 前景", "in-situ ESR prospect"),
    ("原位渗透率测量", "in-situ permeability measurement"),
    ("质量输运机制", "mass transport mechanisms"),
    ("物理结构转变", "transformation of physical structures"),
    ("中试与商业化", "validation / commercialisation of lab-scale coke oven"),
    ("实际炼焦条件", "practical coking conditions"),
    ("焦化压力", "coking pressure"),
    ("焦化时间", "coking time"),
    ("焦化产率", "coke yield"),
    ("加热速率", "heating rate"),
    ("焦炭反应性", "coke reactivity index (CRI)"),
    ("焦炭反应性指数", "CRI (Coke Reactivity Index)"),
    ("CRI", "CRI (coke reactivity index)"),
    ("反应性", "CRI / reactivity"),
    ("反应后强度", "coke strength after reaction (CSR)"),
    ("焦炭反应后强度", "CSR (Coke Strength after Reaction)"),
    ("CSR", "CSR (coke strength after reaction)"),
    ("焦炭质量参数", "coke quality parameters (CRI, CSR)"),
    ("转鼓指数", "Micum drum index (M10/M25/M40)"),
    ("抗碎强度", "abrasion resistance / drum strength"),
    ("光学组织", "coke optical texture"),
    ("各向异性", "anisotropy"),
    ("冶金性能指数", "metallurgical property index"),
    ("焦炭水分含量", "coke moisture content"),
    ("焦末", "coke breeze"),
    ("再固化", "resolidification"),
    ("镜质组熔融", "vitrinite maceral fusion"),
    ("低流动度惰质组富集煤", "low fluidity inertinite-rich coal"),
    ("高流动度镜质组富集煤", "high fluidity vitrinite-rich coal"),
    ("煤性质与焦炭质量的定量关系", "quantitative linking of coal properties to coke quality"),
    ("焦炭质量预测", "predicting coke quality (strength, reactivity)"),
    ("配煤机制", "coal blending mechanisms"),
    ("焦炭形成方法", "coke formation methodology"),
    ("综合研究焦化行为", "integrated study of coking behaviors"),
    ("协同掺杂效应", "doping synergy"),
    ("副产品回收", "by-product recovery"),
    ("固态 13C NMR", "solid-state 13C NMR"),
    ("固态 13C NMR 谱学", "solid-state 13C NMR spectroscopy"),
    ("13C NMR 谱图分析", "13C NMR spectral analysis"),
    ("Bruker AVANCE HD500", "Bruker AVANCE HD500"),
    ("魔角自旋(MAS)", "magic angle spinning (MAS)"),
    ("接触时间(CP)", "contact time (CP)"),
    ("化学位移", "chemical shift"),
    ("自旋-晶格弛豫时间(T1)", "spin-lattice relaxation time (T1)"),
    ("傅立叶变换红外光谱", "Fourier-transform infrared spectroscopy (FTIR)"),
    ("同步辐射红外光谱", "Synchrotron infrared spectroscopy (Synchrotron IR)"),
    ("同步辐射红外表征", "Synchrotron IR characterization"),
    ("Bruker Vertex 80v FTIR 显微镜", "Bruker Vertex 80v FTIR microscope"),
    ("光谱曲线拟合", "curve-fitting of spectra"),
    ("芳香 vs 脂肪族结构对比", "aromatic vs. aliphatic structures"),
    ("同步辐射 micro-CT", "Synchrotron micro-CT"),
    ("同步辐射微焦 CT(SMCT)", "synchrotron micro-CT (SMCT)"),
    ("SMCT 分析", "synchrotron micro-CT (SMCT) analysis"),
    ("X 射线 CT", "X-ray computed tomography (XRCT)"),
    ("μ 焦点 X 射线 CT", "μ–focus X-ray CT"),
    ("3D 图像分析(GeoDict)", "3D image analysis (GeoDict)"),
    ("3D 图像分析软件(GeoDict)", "3D image analysis software (GeoDict)"),
    ("3D 微结构重构", "3D microstructure reconstruction"),
    ("水平切片", "horizontal slicing"),
    ("空隙隔离分析", "isolation of voids"),
    ("扫描电镜", "scanning electron microscope (SEM)"),
    ("SEM-EDS 分析", "SEM-EDS analysis"),
    ("小角 X 射线散射", "small-angle X-ray scattering (SAXS)"),
    ("小角中子散射", "small-angle neutron scattering (SANS)"),
    ("X 射线衍射", "X-ray diffraction (XRD)"),
    ("焦炭 XRD", "X-ray diffraction (XRD) of cokes"),
    ("电子顺磁共振", "electron paramagnetic resonance (EPR)"),
    ("顺磁中心", "paramagnetic centers"),
    ("热重分析", "TGA (thermogravimetric analysis)"),
    ("热重-质谱联用", "TG-MS (thermogravimetric-mass spectrometry)"),
    ("热膨胀分析", "thermodilatometry (TDA)"),
    ("微型气相色谱", "micro-GC"),
    ("微型气相色谱(micro-GC)", "micro gas chromatography (micro-GC)"),
    ("固定床热解实验", "fixed-bed pyrolysis experiment"),
    ("标准气体校准", "calibration with standard gas mixture"),
    ("水冷凝器", "water condenser"),
    ("二氯乙烷捕集器", "dichloroethane trap"),
    ("热导检测器(TCD)", "thermal conductivity detector (TCD)"),
    ("分子筛色谱柱(MS5A)", "molecule sieve column (MS5A)"),
    ("Polar Plot U(PPU)色谱柱", "Polar Plot U (PPU) column"),
    ("光气分析", "light gas analysis"),
    ("热解产物分析", "pyrolysate analysis"),
    ("甲烷释出曲线", "methane release profile"),
    ("氢气释出曲线", "hydrogen release profile"),
    ("挥发分释出曲线", "volatiles release curve"),
    ("分布活化能模型(DAEM)", "distributed activation energy model (DAEM)"),
    ("互相关分析", "cross-correlation analysis"),
    ("相关系数 r", "correlation coefficient (r)"),
    ("氦比重测定", "He-gas pycnometry"),
    ("先进分析技术(ESR 等)", "advanced analytical techniques (ESR, etc.)"),
    ("碳中和", "carbon neutrality"),
    ("生命周期评价", "LCA (life cycle assessment)"),
    ("二氧化碳减排", "CO2 emission reduction"),
    ("生物质焦", "biomass char / biochar"),
    ("固碳", "carbon fixation / sequestration"),
]
# 按 key 长度降序排,长词优先匹配
_CN2EN_TERMS = sorted(_CN2EN_TERMS_RAW, key=lambda kv: -len(kv[0]))


def _preprocess_cn_terms(q: str) -> str:
    """把中文焦化术语预替换为标准英文,防止 LLM 翻错。

    例:"捣固焦工艺有哪些影响因素"
       → "tamping coke / non-recovery coke / stamped coke 工艺有哪些影响因素"
    LLM 拿到这种中英混合 query 时,会保留已有的英文术语,只翻剩余中文部分。
    """
    out = q
    for cn, en in _CN2EN_TERMS:
        if cn in out:
            out = out.replace(cn, f" {en} ")
    # 清理多余空格
    out = re.sub(r"\s+", " ", out).strip()
    return out


_TRANSLATE_PROMPT = """You are a bilingual assistant for a coal coking domain Q&A system.

The user question may have key Chinese terms already pre-translated to standard
English (e.g. "tamping coke", "CRI", "vitrinite"). Keep those English terms verbatim.

If conversation history is provided, FIRST resolve coreferences (它/这/那/这个/那种 etc.)
and ellipsis using the history. Replace pronouns with concrete entities.
Examples:
  - history: "user: 焦炭 CSR 是怎么测的"
    current: "它和挥发分什么关系"
    → resolved: "焦炭 CSR 和挥发分的关系"
  - history: "user: 介绍一下 Zofiówka 煤"
    current: "那种煤有什么特点"
    → resolved: "Zofiówka 煤的特点"
  - history: "user: 煤的镜质组反射率怎么算"
    current: "标准是多少"
    → resolved: "镜质组反射率的标准范围"

Your job:
1. **Resolve coreferences** using conversation history (if any).
2. **Normalize question form** to standardized academic search phrasing:
   - "怎么测/如何测定" → "measurement method / standard test procedure"
   - "有什么影响/有哪些影响" → "effects of X on Y / influence of"
   - "是什么/什么是" → "definition / concept of"
   - "为什么" → "mechanism / cause / reason"
   - 把口语化问题转成论文标题/章节风格的查询
3. Generate **2-3 diverse** English search queries from different angles
   (one general, one process/mechanism-focused, one property/measurement-focused).
4. Extract key domain concepts/entities for knowledge graph lookup.

Return a JSON object:
{
  "english_queries": ["query1", "query2", "query3"],
  "key_concepts": ["CSR", "coal fluidity", "vitrinite"],
  "key_methods": ["FTIR", "TG-MS"],
  "key_materials": ["coking coal", "semi-coke"],
  "resolved_question": "the question after resolving pronouns (in Chinese, for logging)"
}

Rules:
- ALWAYS return at least 2 english_queries with different phrasings.
- Use standard academic terminology and abbreviations (CSR, CRI, FTIR, TGA, etc.).
- If the input is already in English, still generate optimized queries.
- Return ONLY the JSON object, no markdown fences, no explanation."""


def translate_query(question: str, history: list[dict] | None = None) -> dict:
    """
    Translate a Chinese question into English search queries and extract key concepts.

    Args:
        question: 当前用户问题
        history: 多轮对话历史,格式 [{"user_message": "...", "bot_response": "..."}],
                按时间顺序(老的在前)。最多取最近 3 轮塞进 LLM context。

    Returns:
        {
            "english_queries": [q1, q2, q3],
            "key_concepts": [...],
            "key_methods": [...],
            "key_materials": [...],
            "resolved_question": "...(用 history 补全代词后的问题)"
        }
    """
    # 1) 术语预替换 — 兜底候选,即便 LLM 翻车也保留正确术语
    pre_q = _preprocess_cn_terms(question)

    fallback = {
        "english_queries": [pre_q] if pre_q else [question],
        "key_concepts": [],
        "key_methods": [],
        "key_materials": [],
        "resolved_question": question,
    }

    # 2) 拼装 LLM messages: system_prompt + (最近 3 轮 history) + 当前问题
    messages = [{"role": "system", "content": _TRANSLATE_PROMPT}]
    if history:
        # 最近 3 轮,bot_response 截断到 500 字防 prompt 爆
        for h in history[-3:]:
            user_msg = (h.get("user_message") or "").strip()
            bot_msg = (h.get("bot_response") or "").strip()[:500]
            if user_msg:
                messages.append({"role": "user", "content": user_msg})
            if bot_msg:
                messages.append({"role": "assistant", "content": bot_msg})
    messages.append({"role": "user", "content": pre_q})

    try:
        raw = chat_json(messages, temperature=0.3)
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
    except Exception:
        return fallback

    en_qs = data.get("english_queries") or []
    if not isinstance(en_qs, list):
        en_qs = [str(en_qs)]
    # 去空、去重
    seen = set()
    cleaned = []
    for q in en_qs:
        q = str(q).strip()
        if q and q not in seen:
            seen.add(q)
            cleaned.append(q)
    # 把术语预替换版本也加进候选(放最前,作为最强保底)
    if pre_q != question and pre_q not in seen:
        cleaned = [pre_q] + cleaned
    if not cleaned:
        cleaned = [pre_q or question]
    # 截到 3 个,避免下游召回开销过大
    cleaned = cleaned[:3]

    return {
        "english_queries": cleaned,
        "key_concepts": data.get("key_concepts") or [],
        "key_methods": data.get("key_methods") or [],
        "key_materials": data.get("key_materials") or [],
        "resolved_question": data.get("resolved_question") or question,
    }
