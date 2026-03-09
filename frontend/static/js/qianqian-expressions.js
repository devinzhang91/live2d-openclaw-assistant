/**
 * Qianqian 模型表情映射配置
 * 
 * 基于 qianqian.model3.json 中的 31 个表情
 * 每个表情对应一个 .exp3.json 文件，控制特定的 Live2D 参数
 * 
 * 表情分类：
 * - 眼部表情：各种眼睛特效（星星眼、爱心眼等）
 * - 面部红晕：脸红、黑脸等
 * - 情绪表达：开心、生气、无语等
 * - 嘴部动作：嘟嘴、鼓嘴、吐舌等
 * - 发型切换：长发、双马尾、垂耳
 * - 道具互动：扇子、话筒、笔记本等
 */

// ==================== 完整表情映射 ====================

/**
 * 表情ID到中文名的映射
 * 用于在代码中直观理解每个表情的含义
 */
const QIANQIAN_EXPRESSION_NAMES = {
    // === 眼部特效 (Eye Effects) ===
    'expression1':  { name: '星星眼', param: 'Param53', file: 'xingxingyan.exp3.json', emoji: '✨', desc: '闪烁的星星眼睛' },
    'expression12': { name: '爱心眼', param: 'Param66', file: 'aixinyan.exp3.json', emoji: '❤️', desc: '充满爱意的眼睛' },
    'expression13': { name: '轮回眼', param: 'Param67', file: 'lunhuiyan.exp3.json', emoji: '🔮', desc: '神秘轮回眼特效' },
    'expression14': { name: '空白眼', param: 'Param68', file: 'kongbaiyan.exp3.json', emoji: '👀', desc: '空白无神的眼睛' },
    'expression6':  { name: '眼珠', param: 'Param57', file: 'yanzhu.exp3.json', emoji: '👁️', desc: '突出的眼珠效果' },
    'expression11': { name: '钱眼', param: 'Param64', file: 'qianyan.exp3.json', emoji: '💰', desc: '财迷眼特效' },
    
    // === 面部红晕 (Face Blush) ===
    'expression2':  { name: '脸红', param: 'Param54', file: 'lianhong.exp3.json', emoji: '😳', desc: '普通脸红' },
    'expression3':  { name: '脸红2', param: 'Param69', file: 'lianhong2.exp3.json', emoji: '🥰', desc: '更深的脸红' },
    'expression4':  { name: '黑脸', param: 'Param55', file: 'heilian.exp3.json', emoji: '🌚', desc: '发黑的脸色' },
    
    // === 情绪表达 (Emotions) ===
    'expression5':  { name: '眼泪', param: 'Param56', file: 'yanlei.exp3.json', emoji: '😢', desc: '哭泣流泪' },
    'expression9':  { name: '流汗', param: 'Param59', file: 'liuhan.exp3.json', emoji: '😅', desc: '尴尬流汗' },
    'expression10': { name: '无语', param: 'Param87', file: 'wuyu.exp3.json', emoji: '😑', desc: '无语凝噎' },
    'expression19': { name: '生气', param: 'Param90', file: 'shengqi.exp3.json', emoji: '😠', desc: '愤怒表情' },
    'expression18': { name: '星星', param: 'Param89', file: 'xingxing.exp3.json', emoji: '🌟', desc: '身边有星星环绕' },
    
    // === 疑惑表情 (Confusion) ===
    'expression7':  { name: '问号', param: 'Param58', file: 'wenhao.exp3.json', emoji: '❓', desc: '头顶问号' },
    'expression8':  { name: '问号2', param: 'Param88', file: 'wenhao2.exp3.json', emoji: '❔', desc: '侧面问号' },
    
    // === 嘴部动作 (Mouth Actions) ===
    'expression15': { name: '吐舌', param: 'Param70', file: 'tushe.exp3.json', emoji: '😛', desc: '调皮吐舌' },
    'expression16': { name: '嘟嘴', param: 'Param76', file: 'duzui.exp3.json', emoji: '😗', desc: '嘟嘴卖萌' },
    'expression17': { name: '鼓嘴', param: 'Param83', file: 'guzui.exp3.json', emoji: '😤', desc: '生气鼓嘴' },
    
    // === 发型切换 (Hairstyles) ===
    'expression20': { name: '长发', param: 'Param84', file: 'changfa.exp3.json', emoji: '💇', desc: '切换为长发造型' },
    'expression21': { name: '双马尾', param: 'Param85', file: 'shuangmawei.exp3.json', emoji: '🎀', desc: '切换为双马尾' },
    'expression22': { name: '垂耳', param: 'Param86', file: 'chuier.exp3.json', emoji: '🐰', desc: '切换为垂耳造型' },
    
    // === 道具/物品 (Items) ===
    'expression23': { name: '镜子', param: 'Param95', file: 'jingzi.exp3.json', emoji: '🪞', desc: '手持镜子' },
    'expression24': { name: '狐狸', param: 'Param96', file: 'huli.exp3.json', emoji: '🦊', desc: '身边有狐狸' },
    'expression25': { name: '笔记本R', param: 'Param97', file: 'bijiben.exp3.json', emoji: '📓', desc: '右手拿笔记本' },
    'expression26': { name: '笔记本L', param: 'Param98', file: 'bijiben2.exp3.json', emoji: '📔', desc: '左手拿笔记本' },
    'expression27': { name: '打游戏', param: 'Param99', file: 'dayouxi.exp3.json', emoji: '🎮', desc: '玩游戏姿势' },
    'expression28': { name: '抱狐狸', param: 'Param100', file: 'baohuli.exp3.json', emoji: '🤗', desc: '抱着狐狸玩偶' },
    'expression29': { name: '扇子', param: 'Param101', file: 'shanzi.exp3.json', emoji: '🪭', desc: '手持扇子' },
    'expression30': { name: '话筒', param: 'Param102', file: 'huatong.exp3.json', emoji: '🎤', desc: '手持话筒' },
    'expression31': { name: '比心', param: 'Param103', file: 'bixin.exp3.json', emoji: '🫰', desc: '比心手势' },
};

// ==================== 语义化表情名称映射 ====================

/**
 * 语义名称到 expression ID 的映射
 * 用于代码中直观设置表情，如: playExpression('happy')
 */
const QIANQIAN_EXPRESSION_MAP = {
    // === 基础状态 ===
    'idle': 'expression1',          // 星星眼（默认状态）
    'default': 'expression1',       // 星星眼
    'normal': 'expression1',        // 星星眼
    
    // === 正面情绪 ===
    'happy': 'expression5',         // 眼泪（开心的眼泪）
    'joy': 'expression5',           // 眼泪
    'love': 'expression12',         // 爱心眼
    'loving': 'expression12',       // 爱心眼
    'excited': 'expression18',      // 星星
    'playful': 'expression15',      // 吐舌
    
    // === 害羞/尴尬 ===
    'shy': 'expression2',           // 脸红
    'blush': 'expression2',         // 脸红
    'embarrassed': 'expression9',   // 流汗
    'awkward': 'expression9',       // 流汗
    'shy2': 'expression3',          // 脸红2（更深）
    
    // === 负面情绪 ===
    'sad': 'expression5',           // 眼泪
    'cry': 'expression5',           // 眼泪
    'crying': 'expression5',        // 眼泪
    'angry': 'expression19',        // 生气
    'mad': 'expression19',          // 生气
    'annoyed': 'expression10',      // 无语
    'speechless': 'expression10',   // 无语
    'dark': 'expression4',          // 黑脸
    
    // === 疑惑/思考 ===
    'thinking': 'expression7',      // 问号
    'confused': 'expression7',      // 问号
    'question': 'expression7',      // 问号
    'thinking2': 'expression8',     // 问号2
    
    // === 卖萌/可爱 ===
    'pout': 'expression16',         // 嘟嘴
    'cute': 'expression16',         // 嘟嘴
    'puffed': 'expression17',       // 鼓嘴
    
    // === 特殊眼部 ===
    'starry': 'expression1',        // 星星眼
    'money': 'expression11',        // 钱眼
    'reincarnation': 'expression13', // 轮回眼
    'blank': 'expression14',        // 空白眼
    'eyeball': 'expression6',       // 眼珠
    
    // === 监听/专注 ===
    'listening': 'expression1',     // 星星眼（专注）
    'focused': 'expression1',       // 星星眼
    
    // === 道具相关 ===
    'mirror': 'expression23',       // 镜子
    'fox': 'expression24',          // 狐狸
    'notebook': 'expression25',     // 笔记本
    'gaming': 'expression27',       // 打游戏
    'hug': 'expression28',          // 抱狐狸
    'fan': 'expression29',          // 扇子
    'mic': 'expression30',          // 话筒
    'microphone': 'expression30',   // 话筒
    'heart': 'expression31',        // 比心
    
    // === 发型 ===
    'longhair': 'expression20',     // 长发
    'twintail': 'expression21',     // 双马尾
    'droopears': 'expression22',    // 垂耳
};

// ==================== 表情分组配置 ====================

/**
 * 表情分组 - 用于随机选择或场景切换
 * 每个分组包含一组相关的表情ID
 */
const QIANQIAN_EXPRESSION_GROUPS = {
    // === 基础分组 ===
    'Idle': [
        'expression1',   // 星星眼
        'expression7',   // 问号
        'expression8',   // 问号2
        'expression12',  // 爱心眼
        'expression13',  // 轮回眼
        'expression18',  // 星星
    ],
    
    'Listening': [
        'expression1',   // 星星眼
        'expression7',   // 问号
        'expression12',  // 爱心眼
        'expression18',  // 星星
    ],
    
    'Thinking': [
        'expression2',   // 脸红
        'expression3',   // 脸红2
        'expression4',   // 黑脸
        'expression7',   // 问号
        'expression8',   // 问号2
        'expression10',  // 无语
        'expression11',  // 钱眼
    ],
    
    // === 情绪分组 ===
    'Happy': [
        'expression5',   // 眼泪（开心的）
        'expression6',   // 眼珠
        'expression12',  // 爱心眼
        'expression15',  // 吐舌
        'expression16',  // 嘟嘴
        'expression18',  // 星星
        'expression31',  // 比心
    ],
    
    'Sad': [
        'expression5',   // 眼泪
        'expression14',  // 空白眼
    ],
    
    'Angry': [
        'expression4',   // 黑脸
        'expression17',  // 鼓嘴
        'expression19',  // 生气
    ],
    
    'Worried': [
        'expression9',   // 流汗
        'expression10',  // 无语
        'expression14',  // 空白眼
    ],
    
    'Confused': [
        'expression7',   // 问号
        'expression8',   // 问号2
        'expression10',  // 无语
    ],
    
    'Shy': [
        'expression2',   // 脸红
        'expression3',   // 脸红2
        'expression9',   // 流汗
    ],
    
    // === 特殊分组 ===
    'EyeEffects': [
        'expression1',   // 星星眼
        'expression6',   // 眼珠
        'expression11',  // 钱眼
        'expression12',  // 爱心眼
        'expression13',  // 轮回眼
        'expression14',  // 空白眼
    ],
    
    'Hairstyles': [
        'expression20',  // 长发
        'expression21',  // 双马尾
        'expression22',  // 垂耳
    ],
    
    'WithItems': [
        'expression23',  // 镜子
        'expression24',  // 狐狸
        'expression25',  // 笔记本R
        'expression26',  // 笔记本L
        'expression27',  // 打游戏
        'expression28',  // 抱狐狸
        'expression29',  // 扇子
        'expression30',  // 话筒
        'expression31',  // 比心
    ],
    
    'Cute': [
        'expression12',  // 爱心眼
        'expression15',  // 吐舌
        'expression16',  // 嘟嘴
        'expression18',  // 星星
        'expression31',  // 比心
    ],
};

// ==================== 便捷函数 ====================

/**
 * 获取表情的详细信息
 * @param {string} exprId - expression ID (如 'expression1')
 * @returns {object} 表情信息对象
 */
function getExpressionInfo(exprId) {
    return QIANQIAN_EXPRESSION_NAMES[exprId] || null;
}

/**
 * 通过语义名称获取 expression ID
 * @param {string} name - 语义名称 (如 'happy', 'love')
 * @returns {string} expression ID
 */
function getExpressionId(name) {
    return QIANQIAN_EXPRESSION_MAP[name] || name;
}

/**
 * 获取分组内的随机表情
 * @param {string} group - 分组名称
 * @returns {string} expression ID
 */
function getRandomExpressionFromGroup(group) {
    const expressions = QIANQIAN_EXPRESSION_GROUPS[group];
    if (!expressions || expressions.length === 0) {
        console.warn('[Expression] 未知表情组:', group);
        return 'expression1';
    }
    return expressions[Math.floor(Math.random() * expressions.length)];
}

/**
 * 列出所有可用表情
 * @returns {Array} 表情列表
 */
function listAllExpressions() {
    return Object.entries(QIANQIAN_EXPRESSION_NAMES).map(([id, info]) => ({
        id,
        ...info
    }));
}

/**
 * 按分类获取表情
 * @param {string} category - 分类名 (EyeEffects/Emotions/Hairstyles/Items)
 * @returns {Array} 表情列表
 */
function getExpressionsByCategory(category) {
    const categoryMap = {
        '眼部特效': ['expression1', 'expression6', 'expression11', 'expression12', 'expression13', 'expression14'],
        '面部红晕': ['expression2', 'expression3', 'expression4'],
        '情绪表达': ['expression5', 'expression9', 'expression10', 'expression18', 'expression19'],
        '疑惑表情': ['expression7', 'expression8'],
        '嘴部动作': ['expression15', 'expression16', 'expression17'],
        '发型切换': ['expression20', 'expression21', 'expression22'],
        '道具互动': ['expression23', 'expression24', 'expression25', 'expression26', 'expression27', 'expression28', 'expression29', 'expression30', 'expression31'],
    };
    
    const ids = categoryMap[category] || [];
    return ids.map(id => ({ id, ...QIANQIAN_EXPRESSION_NAMES[id] }));
}

// ==================== 导出 ====================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        QIANQIAN_EXPRESSION_NAMES,
        QIANQIAN_EXPRESSION_MAP,
        QIANQIAN_EXPRESSION_GROUPS,
        getExpressionInfo,
        getExpressionId,
        getRandomExpressionFromGroup,
        listAllExpressions,
        getExpressionsByCategory,
    };
}
