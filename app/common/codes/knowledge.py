from enum import nonmember, unique

from app.common.codes.base import CodeEnum


@unique
class KnowledgeCode(CodeEnum):
    segment = nonmember((3000, 3999))

    INVALID_PARAMETER = 3000, "知识库请求参数错误"
    DOCUMENT_NOT_FOUND = 3001, "知识文档不存在"
    DOCUMENT_FORBIDDEN = 3002, "无权操作该知识文档"
    DOCUMENT_STATE_INVALID = 3003, "当前文档状态不允许操作"
    UPLOAD_FAILED = 3004, "知识文档上传失败"
    DOCUMENT_DELETE_FAILED = 3005, "知识文档删除失败"
    CHUNK_NOT_FOUND = 3006, "知识 Chunk 不存在"
    CHUNK_UPDATE_FAILED = 3007, "知识 Chunk 操作失败"
    RAW_FILE_UNAVAILABLE = 3008, "知识文档原文件暂不可用"
