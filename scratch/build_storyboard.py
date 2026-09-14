import json
import re
import sys

sys.path.insert(0, 'pipeline')
import workflow_contracts

state = json.load(open('projects/013_影响力/workflow/runs/run_20260913_074757/state.json'))
project_meta = json.load(open('projects/013_影响力/project.json'))
characters = json.load(open('assets/characters.json'))
script_text = open('projects/013_影响力/input/script.txt', encoding='utf-8').read()
script_blocks = workflow_contracts.parse_script(script_text)

def split_voice_2(v):
    mid = len(v) // 2
    candidates = []
    for m in re.finditer(r'[。！？；]', v):
        candidates.append((abs(m.end() - mid), m.end()))
    candidates.sort()
    split_pos = candidates[0][1]
    return [v[:split_pos], v[split_pos:]]

def split_voice_4(v):
    quarter = len(v) // 4
    cuts = [0]
    for target in [quarter, quarter*2, quarter*3]:
        candidates = []
        for m in re.finditer(r'[。！？；]', v):
            pos = m.end()
            if pos > cuts[-1] + 30 and pos < len(v) - 30:
                candidates.append((abs(pos - target), pos))
        candidates.sort()
        cuts.append(candidates[0][1])
    cuts.append(len(v))
    return [v[cuts[i]:cuts[i+1]] for i in range(4)]

# Define visual descriptions, shots, emotions, characters for each beat
# Total 56 beats
beat_specs = [
    # Block 0 (TITLE, 4 beats, hook)
    {"shot": "wide", "scene": "霓虹灯闪烁的商业街夜景", "subject": "被商业广告屏包围的年轻上班族", "action": "走在喧闹街头并看向巨大打折看板", "object": "发光广告牌与手机屏幕", "char": "young_pro", "emotion": "困惑"},
    {"shot": "medium", "scene": "排起长队的网红售楼处大厅", "subject": "焦虑争抢购房名额的购房者", "action": "握紧排队号码牌并向前探身交谈", "object": "闪烁的售罄展板与号码牌", "char": "stressed_worker", "emotion": "焦虑"},
    {"shot": "close", "scene": "明亮安静的学者书房", "subject": "翻阅心理学手稿的西奥迪尼导师", "action": "翻开《影响力》典籍并沉思", "object": "精装书籍与羽毛笔", "char": "author_morgan", "emotion": "专注"},
    {"shot": "wide", "scene": "通透大气的认知展厅全景", "subject": "站在五步认知展板前的年轻上班族", "action": "迈步走向发光的认知防御架构图", "object": "五步架构展板与聚光灯", "char": "young_pro", "emotion": "坚定"},

    # Block 2 (CARD 停不下来的疯狂手指, 2 beats, hook)
    {"shot": "medium", "scene": "深夜昏暗的家庭书房写字台前", "subject": "坐在电脑前精细核算账目的周扬", "action": "按动计算器仔细检查三家网店的比价单", "object": "多栏比价单与记账本", "char": "young_pro", "emotion": "专注"},
    {"shot": "close", "scene": "深夜泛着冷光的家庭卧室床头", "subject": "满头大汗紧握手机的年轻打工人", "action": "按向屏幕上的限时立即付款按键", "object": "倒计时读秒界面与狂闪的支付窗", "char": "stressed_debtor", "emotion": "焦虑"},

    # Block 3 (CARD 拆开快递后的空虚与懊悔, 2 beats, hook)
    {"shot": "medium", "scene": "堆满杂物的家庭玄关走廊", "subject": "蹲在快递堆前拆开包装的周扬", "action": "打开纸箱并拿出毫无用处的名牌外套", "object": "散落的快递盒与崭新夹克", "char": "young_pro", "emotion": "叹气"},
    {"shot": "close", "scene": "清冷月光下的家庭客厅窗边", "subject": "凝视手机账单悔恨不已的年轻男子", "action": "凝视被扣掉大半月薪水的账单界面", "object": "长条消费明细与红字透支提示", "char": "young_pro", "emotion": "焦虑"},

    # Block 4 (CARD 资产泡沫中的从众狂热, 2 beats, hook)
    {"shot": "wide", "scene": "人头攒动的热门资产交易大厅", "subject": "被狂热人群推搡包围的普通散户", "action": "进入拥挤大厅并注视翻红的行情大屏", "object": "红色暴涨数字与蜂拥的人潮", "char": "stressed_worker", "emotion": "惊慌"},
    {"shot": "medium", "scene": "气氛紧绷的理财中介接待台前", "subject": "倾听中介极速推销的周扬", "action": "倾听中介高声呼喊并犹豫着递出银行卡", "object": "最后保留房源合同与POS机", "char": "young_pro", "emotion": "犹豫"},

    # Block 5 (QUOTE 为什么聪明人也会被洗劫？, 2 beats, hook)
    {"shot": "medium", "scene": "阳光洒入的家庭学术讲堂", "subject": "身着深色西装的西奥迪尼导师", "action": "指向黑板上画出的人类大脑直觉回路", "object": "粉笔图解与心理学教具", "char": "author_morgan", "emotion": "自信"},
    {"shot": "close", "scene": "机械运转的复古发条实验室", "subject": "自动按下播放键的发条磁带机", "action": "按动红色启动开关并自动运转齿轮", "object": "Click-Whirr机械装置与磁带", "char": "none", "emotion": "平静"},

    # Block 6 (CARD 审视你的决策自主权, 2 beats, hook)
    {"shot": "medium", "scene": "静谧反思的家庭书房飘窗前", "subject": "手捧热茶陷入反思的周扬", "action": "沉思过去一年的账单与消费诱惑", "object": "白纸上的决策自省清单与茶杯", "char": "young_pro", "emotion": "沉思"},
    {"shot": "wide", "scene": "晨光熹微的城市天桥中央", "subject": "停下脚步审视车流的年轻上班族", "action": "注视桥下奔流不息的早高峰人群", "object": "远方朝阳与整齐前行的人潮", "char": "young_pro", "emotion": "平静"},

    # Block 8 (CARD 病灶一：按键式盲从 Click-Whirr, 2 beats, insight)
    {"shot": "wide", "scene": "荒凉原始的远古草原模拟展区", "subject": "守护巢穴的雌性火鸡模型", "action": "倾听雏鸟叫声并本能地张开羽翼哺育", "object": "草丛鸟巢与模拟发声装置", "char": "none", "emotion": "平静"},
    {"shot": "medium", "scene": "现代数字化商场中庭走廊", "subject": "手持优惠遥控器的狡黠营销员", "action": "操作遥控器并指向被催眠般前行的顾客", "object": "红外遥控器与闪烁的折扣标识", "char": "stressed_debtor", "emotion": "冷酷"},

    # Block 9 (CARD 病灶二：社会认同与盲从假象, 2 beats, insight)
    {"shot": "wide", "scene": "人流密集的商业广场转角", "subject": "在网红店铺门前排长队的人造托儿", "action": "走入队伍并在店员示意下刻意放慢步伐", "object": "引导隔离栏与虚假的排队号码牌", "char": "stressed_worker", "emotion": "麻木"},
    {"shot": "medium", "scene": "闪烁蓝光的直播运营监控中心", "subject": "疯狂敲击键盘的虚假水军运营者", "action": "按动键盘发送成百上千条虚假的抢到弹幕", "object": "多联监控屏幕与自动化刷单软件", "char": "stressed_debtor", "emotion": "专注"},

    # Block 10 (CARD 病灶三：稀缺法则与心理抗拒, 2 beats, insight)
    {"shot": "medium", "scene": "高档奢侈品陈列展厅玻璃柜台", "subject": "被玻璃牢笼紧紧锁住的限量版鞋盒", "action": "拉动铁链将限量商品高高悬挂展示", "object": "特制防盗玻璃罩与限量专属编码", "char": "none", "emotion": "平静"},
    {"shot": "close", "scene": "气氛压抑的拍卖会举牌席前", "subject": "因害怕失去购买资格而焦灼的买家", "action": "握紧号码牌并在拍卖师催促下果断举牌", "object": "即将落下的拍卖木槌与举号牌", "char": "young_pro", "emotion": "焦虑"},

    # Block 11 (CARD 病灶四：致命毒药：竞争性稀缺, 2 beats, insight)
    {"shot": "wide", "scene": "拥挤窒息的二手车看车现场", "subject": "被车商故意约在同一时刻的三位买家", "action": "互相对话争夺并试图抢先交纳定金", "object": "二手汽车车前盖与购车意向协议", "char": "stressed_worker", "emotion": "愤怒"},
    {"shot": "close", "scene": "神经生物学医学三维投影视室", "subject": "被情绪风暴接管的人脑神经结构", "action": "注视被红色杏仁核完全压制的理智灰质", "object": "三维大脑全息投影与警戒红光", "char": "author_morgan", "emotion": "警惕"},

    # Block 12 (QUOTE 稀缺无法改变事物的本质, 2 beats, insight)
    {"shot": "medium", "scene": "阳光柔和的极简西点厨房", "subject": "放在纯白瓷盘中央的最后一块饼干", "action": "拿起那块唯一的饼干并仔细端详", "object": "纯白瓷盘与平淡无奇的麦香饼干", "char": "young_pro", "emotion": "平静"},
    {"shot": "wide", "scene": "沙盘模型环绕的奢华售楼中心", "subject": "面对空旷样板间陷入沉思的看房者", "action": "巡视空无一物的毛坯房阳台并叹气", "object": "水泥墙面与烫金宣传单页", "char": "young_pro", "emotion": "沉思"},

    # Block 14 (CARD/TABLE 双轮驱动顺从模型, 2 beats, insight)
    {"shot": "medium", "scene": "光影交织的家庭物理机械工坊", "subject": "精巧咬合旋转的两个巨大金属齿轮", "action": "操作操纵杆使社会认同与稀缺齿轮加速咬合", "object": "刻有认同与稀缺铭文的发光齿轮组", "char": "author_morgan", "emotion": "专注"},
    {"shot": "close", "scene": "狂风呼啸的心理旋涡核心区", "subject": "被齿轮风暴卷入的失控人偶模型", "action": "凝视在咬合压力下逐渐碎裂的理智指针", "object": "碎裂的理性仪表盘与风暴残影", "char": "none", "emotion": "警惕"},

    # Block 15 (CARD 认同放大的两个催化条件, 2 beats, insight)
    {"shot": "wide", "scene": "大雾弥漫的家庭社区十字路口", "subject": "在浓雾中迷失方向的年轻上班族", "action": "走入浓雾并紧随前方模糊人群的脚印", "object": "指引不清的路标与密集的足迹", "char": "young_pro", "emotion": "困惑"},
    {"shot": "medium", "scene": "温暖真实的家庭起居室直播角", "subject": "伪装成普通邻家宝妈的营销主播", "action": "面对镜头微笑交谈并展示手中的爆款战利品", "object": "手机补光灯与温馨的家庭背景布", "char": "frugal_girl", "emotion": "自信"},

    # Block 16 (CARD 稀缺法则的两大心理支柱, 2 beats, insight)
    {"shot": "medium", "scene": "炽热刺眼的斗兽场式售楼现场", "subject": "被大喇叭催促得满脸通红的年轻夫妻", "action": "倾听高音喇叭播报并争抢签约席位", "object": "高音喇叭与最后一套内部房源指示牌", "char": "stressed_worker", "emotion": "焦虑"},
    {"shot": "close", "scene": "硝烟弥漫的胜负决斗台边缘", "subject": "把号码牌当成战旗高高举起的周扬", "action": "握紧号牌并站起身来向全场宣布加价", "object": "烫金号牌与红色的加价指示器", "char": "young_pro", "emotion": "坚定"},

    # Block 17 (CARD 关键断点：占有欲与使用价值解耦, 2 beats, insight)
    {"shot": "medium", "scene": "静止悬浮的概念解剖手术室", "subject": "手持解剖光刀的西奥迪尼学者", "action": "操作光刀隔开占有欲多巴胺与使用价值的连接线", "object": "金色多巴胺光球与沉稳的使用价值基座", "char": "author_morgan", "emotion": "专注"},
    {"shot": "close", "scene": "尘埃落定的空旷储藏间角落", "subject": "被随手丢弃在阴影里的昂贵冲动商品", "action": "注视迅速归零的多巴胺能量读数", "object": "归零的虚拟能量表与蒙尘的商品", "char": "none", "emotion": "平静"},

    # Block 18 (STEPS 认知防御的第一道门, 2 beats, insight)
    {"shot": "wide", "scene": "耸立在狂热风暴前的金属防线大门", "subject": "站在防线大门前的年轻上班族周扬", "action": "打开厚重的大门并直面门外的喧嚣狂潮", "object": "沉重的铸铁大门与明亮的警示灯", "char": "young_pro", "emotion": "坚定"},
    {"shot": "medium", "scene": "被拆解暴露的电商后台机房", "subject": "随意修改数字的人造库存操作员", "action": "在键盘上按动回车随意改写剩余库存量", "object": "后台管理系统与虚假库存输入框", "char": "stressed_debtor", "emotion": "冷酷"},

    # Block 20 (TABLE 防割冷凝工具箱, 2 beats, action)
    {"shot": "wide", "scene": "陈列整齐的家庭认知武器库全景", "subject": "站在三层防割冷凝工具展台前的周扬", "action": "走近展台并伸手检视三件发光的防御装备", "object": "生理警报手环、冷凝沙漏与效用天平", "char": "young_pro", "emotion": "自信"},
    {"shot": "medium", "scene": "清晨阳光洒下的家庭工坊长桌", "subject": "指引工具实操的西奥迪尼导师", "action": "翻开实战防御手册并向周扬讲解流程", "object": "图文并茂的冷凝操作手册与钢笔", "char": "author_morgan", "emotion": "欣慰"},

    # Block 21 (STEPS 第一步：捕捉身体早期警报, 2 beats, action)
    {"shot": "close", "scene": "心跳骤升的紧张决策瞬间", "subject": "突然感受到胃部剧烈紧缩的周扬", "action": "按住胸口并警惕地察觉体内的异常心跳", "object": "闪烁红光的生理预警脉搏仪", "char": "young_pro", "emotion": "警惕"},
    {"shot": "medium", "scene": "闪烁诱惑弹窗的电脑屏幕前", "subject": "强行克制冲动指令的理智青年", "action": "放开紧贴鼠标的右手并在桌前停顿沉思", "object": "闪烁立即抢购字样的屏幕与悬空的手掌", "char": "young_pro", "emotion": "坚定"},

    # Block 22 (STEPS 第二步：执行24小时强制冷凝期, 2 beats, action)
    {"shot": "medium", "scene": "静谧祥和的林荫公园步道", "subject": "关掉手机漫步在绿树下的周扬", "action": "离开嘈杂的商场并在公园长椅上坐下休息", "object": "锁屏的智能手机与飘落的枫叶", "char": "young_pro", "emotion": "平静"},
    {"shot": "close", "scene": "时间缓缓流逝的24小时计时沙漏", "subject": "细沙平稳落下的古典黄铜沙漏", "action": "凝视沙漏中荷尔蒙退潮的平缓刻度", "object": "黄铜沙漏与逐渐平稳的脑电波监视仪", "char": "none", "emotion": "平静"},

    # Block 23 (STEPS 第三步：满大街效用独立性测试, 2 beats, action)
    {"shot": "wide", "scene": "货物充沛的普通家庭便民超市货架前", "subject": "推着购物车穿行在宽敞过道里的周扬", "action": "在堆满同款商品的货架前拿起一件观察", "object": "摆得满满当当的平价货架与购物车", "char": "young_pro", "emotion": "平静"},
    {"shot": "medium", "scene": "剥离社交光环后的极简家庭居室", "subject": "静静端详物品实用价值的年轻男子", "action": "放下没有任何炫耀属性的朴素商品并微笑", "object": "纯实木桌案与剥离标签的物品", "char": "young_pro", "emotion": "自信"},

    # Block 24 (STEPS 第四步：反向证据搜寻与托儿识别, 2 beats, action)
    {"shot": "medium", "scene": "深夜家庭工作台前的调查档案室", "subject": "专注检索客观负面评价的周扬", "action": "翻看搜集到的三份最犀利的行业批评报告", "object": "带红笔批注的调查卷宗与放大镜", "char": "young_pro", "emotion": "专注"},
    {"shot": "wide", "scene": "阳光直射下的商业街假排队现场", "subject": "站在街对面冷眼旁观的清醒观察者", "action": "凝视店员偷偷给托儿发放现金的滑稽场景", "object": "掩人耳目的信封与被识破的人造长队", "char": "young_pro", "emotion": "从容"},

    # Block 25 (CARD 第五步：确立不可妥协的交易底线, 2 beats, action)
    {"shot": "wide", "scene": "群魔乱舞的热门资产竞价大厅", "subject": "将双手从容插进裤兜退后三步的周扬", "action": "迈步退到警戒安全黄线以外并安静伫立", "object": "地面的金黄色安全底线与喧闹的竞价屏", "char": "young_pro", "emotion": "坚定"},
    {"shot": "close", "scene": "固若金汤的财富金库防护闸门前", "subject": "坚守本金安全第一原则的守卫者", "action": "按紧铸钢防护门插销并仔细检查防守底线", "object": "重型合金门栓与本金安全准则铭牌", "char": "young_pro", "emotion": "自信"},

    # Block 27 (CARD 真正的财富是对自我的主权, 2 beats, action)
    {"shot": "wide", "scene": "浩瀚数字洪流冲刷的现代金融广场", "subject": "巍然屹立在数字浪潮中央的周扬", "action": "站稳脚跟并拒绝被翻滚的虚荣泡沫吞没", "object": "呼啸而过的数字代码与耀眼的主权盾牌", "char": "young_pro", "emotion": "坚定"},
    {"shot": "medium", "scene": "阳光澄澈的个人精神堡垒露台", "subject": "独立掌控自己每一笔开销的清醒青年", "action": "写下自主决策的财富宪章并望向晴空", "object": "财富主权宪章卷轴与展翅的和平鸽", "char": "young_pro", "emotion": "从容"},

    # Block 28 (QUOTE 坚决拒绝顺从，捍卫理性尊严, 2 beats, action)
    {"shot": "medium", "scene": "高耸威严的真理殿堂石阶上", "subject": "振臂疾呼的心理学宗师西奥迪尼", "action": "高声呼吁众人拒绝顺从并指向理性的灯塔", "object": "熊熊燃烧的理性火炬与真理石柱", "char": "author_morgan", "emotion": "坚定"},
    {"shot": "close", "scene": "闪烁倒计时陷阱的虚假直播窗口", "subject": "毫不犹豫划走虚假营销窗口的果断手指", "action": "在屏幕上按动退出键关掉虚假促销页面", "object": "瞬间熄灭的促销弹窗与洁净的屏幕", "char": "none", "emotion": "自信"},

    # Block 29 (CARD 不在别人的剧本里拼尽全力, 2 beats, action)
    {"shot": "wide", "scene": "众人狂乱奔跑的竞技跑道分岔口", "subject": "从拥挤跑道中主动退出的周扬", "action": "离开狂奔赛道并在路旁绿荫下驻足看路标", "object": "指示不同方向的路标与奔跑扬起的烟尘", "char": "young_pro", "emotion": "从容"},
    {"shot": "medium", "scene": "微风吹拂的静谧山巅观景台", "subject": "神色舒展远眺群山的独立思考者", "action": "倚靠栏杆眺望辽阔山峦并微笑深呼吸", "object": "原木观景护栏与翻滚的白云", "char": "young_pro", "emotion": "欣慰"},

    # Block 30 (CARD 喧嚣世界中的宁静防线, 2 beats, action)
    {"shot": "wide", "scene": "霓虹灯绚烂迷乱的城市商业中心十字路口", "subject": "步伐从容穿过喧嚣人潮的周扬", "action": "走过闪烁降价广告的商场大屏并从容微笑", "object": "耀眼的商场外立面大屏与川流不息的车流", "char": "young_pro", "emotion": "自信"},
    {"shot": "medium", "scene": "灯火温馨明亮的温暖家庭书房", "subject": "在窗前书桌旁静心阅读的周扬", "action": "翻开书本并在台灯下享受宁静的夜晚时光", "object": "暖黄色台灯、整齐书架与热气腾腾的茶", "char": "young_pro", "emotion": "平静"},

    # Block 31 (STEPS 冲动降临时的三句自问, 2 beats, action)
    {"shot": "close", "scene": "随身携带的智能手机备忘录界面", "subject": "显示三句避坑自问清单的发光手机", "action": "在备忘录里仔细检查三条黄金自问法则", "object": "醒目的三问备忘录清单与跳动的光标", "char": "young_pro", "emotion": "专注"},
    {"shot": "wide", "scene": "晨曦洒满整座城市的金色天际线前", "subject": "迎着初升太阳坚定前行的周扬", "action": "迈开从容步伐走向充满希望的新一天生活", "object": "金色的城市天际线与温暖的朝阳", "char": "young_pro", "emotion": "坚定"}
]

# Build storyboard JSON
storyboard_blocks = []
beat_cursor = 0

for pos, sb in enumerate(script_blocks):
    btype = sb["type"]
    head = sb.get("head", "")
    voice = sb.get("voice") or ""
    vchars = len(voice)

    if btype == "PHASE":
        storyboard_blocks.append({
            "block_idx": pos,
            "type": btype,
            "head": head,
            "voice_chars": 0,
            "subtitles": [],
            "beats": []
        })
        continue

    if btype == "END":
        storyboard_blocks.append({
            "block_idx": pos,
            "type": btype,
            "head": head,
            "voice_chars": 0,
            "subtitles": [],
            "beats": [{
                "beat_idx": 0,
                "shot": "wide",
                "visual_description": "场景：晴空万里的大地全景；主体：迎风驻足在山巅平台的周扬；动作：微笑着迈步走向开阔的远方地平线；关键物件：金色朝阳与延伸向无限远方的辽阔长路",
                "sentence_ids": [],
                "start_char": 0,
                "end_char": 0,
                "character_ids": ["young_pro"],
                "emotion": "希望",
                "segment": "action"
            }]
        })
        continue

    if pos == 0:
        sub_texts = split_voice_4(voice)
    else:
        sub_texts = split_voice_2(voice)

    subtitles = []
    c_start = 0
    for sid, stext in enumerate(sub_texts):
        c_end = c_start + len(stext)
        subtitles.append({
            "id": sid,
            "text": stext,
            "start_char": c_start,
            "end_char": c_end
        })
        c_start = c_end

    beats = []
    # Determine segment
    if pos == 0 or pos <= 6:
        seg = "hook"
    elif pos <= 18:
        seg = "insight"
    else:
        seg = "action"

    for b_idx, sub in enumerate(subtitles):
        spec = beat_specs[beat_cursor]
        beat_cursor += 1
        vdesc = f"场景：{spec['scene']}；主体：{spec['subject']}；动作：{spec['action']}；关键物件：{spec['object']}"
        beats.append({
            "beat_idx": b_idx,
            "shot": spec["shot"],
            "visual_description": vdesc,
            "sentence_ids": [sub["id"]],
            "start_char": sub["start_char"],
            "end_char": sub["end_char"],
            "character_ids": [spec["char"]],
            "emotion": spec["emotion"],
            "segment": seg
        })

    storyboard_blocks.append({
        "block_idx": pos,
        "type": btype,
        "head": head,
        "voice_chars": vchars,
        "subtitles": subtitles,
        "beats": beats
    })

storyboard_data = {
    "version": 1,
    "blocks": storyboard_blocks
}

print(f"Total blocks: {len(storyboard_blocks)}, total beats: {beat_cursor}")

problems = workflow_contracts.validate_storyboard(
    storyboard_data,
    script_blocks=script_blocks,
    known_character_ids=set(characters.keys()),
    enforce_density=True,
    project_meta=project_meta,
    enforce_visual_diversity=True,
    enforce_visual_quality=True
)

print(f"Validation problems ({len(problems)}):")
for p in problems:
    print(" -", p)

if not problems:
    out_path = "projects/013_影响力/input/candidates/run_20260913_074757/storyboard/storyboard.json"
    import os
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(storyboard_data, f, ensure_ascii=False, indent=2)
    print(f"Written successfully to {out_path}")
