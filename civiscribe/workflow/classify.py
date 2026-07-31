"""Conservative node-family classification shared by scanner stages."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import ResourceKind, ResourceRole
from .graph import as_link_reference
from .model import PromptNode

_COMFYROLL_MODEL_SLOT_COUNT = 5
_EASY_LORA_SLOT_COUNT = 50
_KNOWN_SAMPLER_PROVIDER_CLASSES = frozenset(
    {
        "clownsampler",
        "clownsampleradvanced",
        "clownsampleradvancedbeta",
        "clownsamplerbeta",
        "detaildaemonsamplernode",
        "legacyclownsampler",
        "ltxfloweditsampler",
        "ltxrfforwardodesampler",
        "samplerdpmadaptative",
        "samplerdpmpp2msde",
        "samplerdpmpp2sancestral",
        "samplerdpmpp3msde",
        "samplerdpmppsde",
        "samplerersde",
        "samplerarvideo",
        "samplereulerancestral",
        "samplereulerancestralcfgpp",
        "samplereulercfgpp",
        "samplerlcm",
        "samplerlms",
        "samplerpipe",
        "samplersasolver",
        "samplerseeds2",
        "samplerselfrefinevideo",
        "voidsampler",
        "sageadvsamplerinfo",
        "sagesamplerinfo",
        "sagesamplerinfonocfg",
        "sagesamplerselector",
        "sageschedulerselector",
        "samplerloaderjk",
        "wanwrappersamplerdefaultjk",
        "easypresampling",
        "easypresamplingadvanced",
        "easypresamplingcascade",
        "easypresamplingcustom",
        "easypresamplingdynamiccfg",
        "easypresamplinglayerdiffusion",
        "easypresamplingnoisein",
        "easypresamplingsdturbo",
        "easylatentnoisy",
    }
)

_SPECIAL_RESOURCE_CLASSES = frozenset(
    {
        # These current integrated loaders choose resources from modes or
        # override links, so a placeholder-only Registry audit cannot exercise
        # their runtime selection logic.
        "h4completeloader",
        "h4universalloader",
        "embeddingpickermultijk",
        "hy3dmodelloader",
        "hy3dvaeloader",
        "loadnanchaku",
        "modelassembler",
        "sageflexibleclipselector",
        "sagemultiselectorflexibleclip",
        "sdvnloadcheckpoint",
        "sdvnloadcheckpointfilter",
        "sumloadadv",
        # Current TA Nodes unified loader uses a typed prefix inside model_file
        # to select checkpoints, diffusion models, or GGUF UNets.
        "taloadmodelwithname",
        # Sage LoRA stacks preserve enabled zero-strength entries and therefore
        # require package-specific extraction instead of the generic stack rule.
        "sagelorastack",
        "sageninelorastack",
        "sagequicklorastack",
        "sagequickninelorastack",
        "sagequicksixlorastack",
        "sagesixlorastack",
        "sagetriplelorastack",
        "sagetriplequicklorastack",
    }
)
_KNOWN_REVIEWED_NON_RESOURCE_CLASSES = frozenset(
    {
        "blackpatchretryhookprovider",
        "blipmodelloader",
        "addlatentguide",
        "bnkgetsigma",
        "checkpointperturbweights",
        "checkpointsave",
        "clipsegmodelloader",
        "clownstyleattnunet",
        "clownstyleblockunet",
        "clownstyleresblockunet",
        "clownstylespatialblockunet",
        "clownstyletransformerblockunet",
        "clownstyleunet",
        "clowninpaint",
        "clowninpaintsimple",
        "condpassthrough",
        "coremldetailerhookprovider",
        "crlatentbatchsize",
        "customsamplerdetailerhookprovider",
        "denoiseschedulerdetailerhookprovider",
        "detailerhookcombine",
        "downloadandloadclipseg",
        "downloadandloadnlfmodel",
        "downloadandloadwav2vecmodel",
        "checkpointnameselector",
        "checkpointselectornode",
        "diffusionmodelselectornode",
        "d2pipe",
        "d2xycheckpointlist",
        "d2xyploteasy",
        "d2xyploteasymini",
        "easydetailerfix",
        "easylatentcompositemaskedwithcond",
        "fantasytalkingmodelloader",
        "fitmasktoimage",
        "frameselect",
        "frameselectlatent",
        "frameselectlatentraw",
        "floattosigmas",
        "imageonlycheckpointsave",
        "groundingdinomodelloadersegmentanything",
        "hunyuanrefinerlatent",
        "hunyuanvideoencodekeyframestocond",
        "imageselectchannel",
        "imageselectcolor",
        "ioloadimageeclipse",
        "lamaremoverdetailerhookprovider",
        "linearquadraticadvanced",
        "ltxvlatentupsampler",
        "ltxvpatchervae",
        "ltxvaddguide",
        "ltxvaddguideadvanced",
        "ltxvaddguidemulti",
        "ltxvaddguidesfrombatch",
        "ltxvaddlatentguide",
        "ltxvcropguides",
        "ltxvimgtovideo",
        "ltxvimgtovideoadvanced",
        "ltxvimgtovideoconditiononly",
        "ltxvimgtovideoinplace",
        "ltxvselectlatents",
        "ltxvreferenceaudio",
        "ltxvsetaudiovideomaskbytime",
        "latentbatcher",
        "latentcrop",
        "llmsampler",
        "llavasampleradvanced",
        "maketrainingdataset",
        "midasmodelloader",
        "multitalkmodelloader",
        "noiseinjectiondetailerhookprovider",
        "previewdetailerhookprovider",
        "prepforunsampling",
        "previewbridgeextendedlatent",
        "previewbridgelatent",
        "pulidevacliploader",
        "pulidevacliploadermultigpu",
        "rebatchlatents",
        "sammodelloader",
        "sammodelloadersegmentanything",
        "sampleroptionsgarbagecollection",
        "sampleroptionstimestepscaling",
        "selectclipdevice",
        "selectmodeldevice",
        "segslabelfilterdetailerhookprovider",
        "segsorderedfilterdetailerhookprovider",
        "segsrangefilterdetailerhookprovider",
        "selectvaedevice",
        "setprecision",
        "setprecisionadvanced",
        "setprecisionuniversal",
        "sigmasfromtext",
        "sigmasmath1",
        "sigmasmath3",
        "torchcompilevae",
        "unetcrossattentionmultiply",
        "unetselfattentionmultiply",
        "unettemporalattentionmultiply",
        "unetsave",
        "unsamplerdetailerhookprovider",
        "vaesave",
        "vaestyletransferlatent",
        "variationnoisedetailerhookprovider",
        "videomamasampler",
        "vhsselecteverynthimage",
        "vhsselecteverynthlatent",
        "vhsselecteverynthmask",
        "vhsselectimages",
        "vhsselectlatents",
        "vhsselectmasks",
        "wan22funcontroltovideo",
        "wananimatetovideo",
        "wancameraembedding",
        "wanhumoimagetovideo",
        "wanimagetovideosvipro",
        "wanmovenative",
        "wanphantomsubjecttovideo",
        "wanscailtovideo",
        "wansoundimagetovideo",
        "wansoundimagetovideoextend",
        "wanvacetovideo",
        "wanvideosamplerextraargs",
        "wanvideoencode",
        "warpeddualcliploader",
        "warpeddualcliploadergguf",
        "warpedvaeloader",
        "wav2vecmodelloader",
        "whispermodelloader",
        "yogurtdiffusionmodelselector",
        "vaeselectornode",
        "easyimagechooser",
        "basemodelparametersjk",
        "ckptloaderjk",
        "saveimagewithmetadatajk",
        "sageaverageconditioning",
        "sagecombineconditioning",
        "upscalemodelloaderjk",
        "vaeloaderjk",
        "sagechromacliploaderfrominfo",
        "sagecliploaderfrominfo",
        "sageloadmodelfrominfo",
        "sagelorastackloader",
        "sagemodellorastackloader",
        "sagestacklorastack",
        "sageunetclipvaetomodelinfo",
        "sageunetloaderfrominfo",
        "sageunetloraloader",
        "sagevaeloaderfrominfo",
    }
)
_EXACT_IMAGE_SAMPLING_STAGE_CLASSES = frozenset(
    {
        "detailerforeach",
        "detailerforeachautoretry",
        "detailerforeachdebug",
        "detailerforeachdebugpipe",
        "detailerforeachpipe",
        "detailerforeachpipeforanimatediff",
        "easypredetailerfix",
        "easypremaskdetailerfix",
        "facedetailer",
        "facedetailerpipe",
        "maskdetailerpipe",
        "segsdetailer",
        "segsdetailerforanimatediff",
        "segsupscaler",
        "segsupscalerpipe",
        "ultimatesdupscale",
        "ultimatesdupscalecustomsample",
        "ultimatesdupscalenoupscale",
    }
)
_DIRECT_IMAGE_GENERATOR_CLASSES = frozenset(
    {
        "briaimageeditnode",
        "bytedanceimagenode",
        "bytedanceseedreamnode",
        "bytedanceseedreamnodev2",
        "diffusersigmvsampler",
        "easystablediffusion3api",
        "flux2imagenode",
        "flux2maximagenode",
        "flux2proimagenode",
        "fluxproexpandnode",
        "fluxprofillnode",
        "fluxproultraimagenode",
        "fluxvtonode",
        "geminiimage2node",
        "geminiimagenode",
        "gemininanobanana2",
        "gemininanobanana2v2",
        "googleaiimagenode",
        "googleainanobanananode",
        "googleaivideogenerator",
        "googleaivideointerpolation",
        "googleaivideostoryboard",
        "grokimageeditnode",
        "grokimageeditnodev2",
        "grokimagenode",
        "ideogramv3",
        "ideogramv4",
        "klingimagegenerationnode",
        "klingomniproimagenode",
        "krea2imagenode",
        "lumaimageeditnode2",
        "lumaimagemodifynode",
        "lumaimagenode",
        "lumaimagenode2",
        "metadatatestsamplerunimeta",
        "openaidalle2",
        "openaidalle3",
        "openaigptimage1",
        "openaigptimagenodev2",
        "pmsgrokimagegen",
        "pmsnanabanana",
        "recraftimageinpaintingnode",
        "recraftimagetoimagenode",
        "recraftreplacebackgroundnode",
        "recrafttexttoimagenode",
        "recraftv4texttoimagenode",
        "reveimagecreatenode",
        "reveimageremixnode",
        "sdwebuiapifallbacknode",
        "sdwebuiapinode",
        "tencent3dtextureeditnode",
        "tencenttexttomodelnode",
        "topazimageenhance",
        "wanimagetoimageapi",
        "wantexttoimageapi",
    }
)
_ANTROBOTS_SAMPLE_INPUTS = frozenset(
    {
        "model",
        "noise_seed",
        "steps",
        "cfg",
        "sampler_name",
        "scheduler",
        "positive",
        "negative",
        "latent_image",
        "denoise",
    }
)
_ANTROBOTS_REFINER_INPUTS = frozenset(
    {
        "base_model",
        "refiner_model",
        "total_steps",
        "refine_step",
        "base_positive",
        "base_negative",
        "refine_positive",
        "refine_negative",
        "base_vae",
        "refine_vae",
        "base_denoise",
        "refine_denoise",
        "seed",
        "cfg",
        "sampler_name",
        "scheduler",
        "latent_image",
    }
)
_ANTROBOTS_REFINER_PIPE_INPUTS = frozenset(
    {
        "base_pipe",
        "refine_pipe",
        "total_steps",
        "refine_step",
        "base_denoise",
        "refine_denoise",
        "seed",
        "cfg",
        "sampler_name",
        "scheduler",
        "image",
        "use_image",
    }
)


def compact_class(node_or_name: PromptNode | str) -> str:
    """Return a comparison-only alphanumeric class label."""

    value = node_or_name.class_type if isinstance(node_or_name, PromptNode) else node_or_name
    return "".join(character for character in value.casefold() if character.isalnum())


def is_antrobots_refiner_node(node: PromptNode) -> bool:
    """Recognize antrobots' direct base/refiner sampler by its full input contract."""

    return compact_class(node) == "refine" and _ANTROBOTS_REFINER_INPUTS.issubset(node.inputs)


def is_antrobots_refiner_pipe_node(node: PromptNode) -> bool:
    """Recognize antrobots' BASIC_PIPE refiner sampler by its full input contract."""

    return compact_class(node) == "refinepipe" and _ANTROBOTS_REFINER_PIPE_INPUTS.issubset(
        node.inputs
    )


def is_sampler_node(node: PromptNode) -> bool:
    """Recognize sampling stages without treating sampler selectors as stages."""

    compact = compact_class(node)
    if compact in {"sample", "refine", "refinepipe"}:
        return (
            _ANTROBOTS_SAMPLE_INPUTS.issubset(node.inputs)
            if compact == "sample"
            else (is_antrobots_refiner_node(node) or is_antrobots_refiner_pipe_node(node))
        )
    if (
        compact
        in {
            "easyunsampler",
            "fluxkohyainferencesampler",
            "regionalsampler",
            "regionalsampleradvanced",
            "samplepipe",
            "samplepipeadvanced",
            "step1xeditgenerate",
            "step1xeditteacachegenerate",
            "twoadvancedsamplersformask",
            "twosamplersformask",
            "wanvideosamplerfromsettings",
            "withanyonesampler",
            "withanyonesamplernode",
        }
        | _EXACT_IMAGE_SAMPLING_STAGE_CLASSES
        | _DIRECT_IMAGE_GENERATOR_CLASSES
    ):
        return True
    if any(marker in compact for marker in ("samplerselect", "samplerprovider", "samplersettings")):
        return False
    if "ksampler" in compact or "samplercustom" in compact:
        return True
    if "sampler" not in compact:
        return False
    has_model_input = any(
        name in node.inputs
        for name in (
            "model",
            "base_model",
            "refiner_model",
            "guider",
            "model_input",
            "diffusion_model",
        )
    )
    has_sampling_input = any(
        name in node.inputs
        for name in (
            "steps",
            "steps_to_run",
            "sampler_name",
            "scheduler",
            "positive",
            "negative",
            "latent_image",
            "noise",
            "sigmas",
        )
    )
    return has_model_input and has_sampling_input


def is_decode_node(node: PromptNode) -> bool:
    """Recognize VAE decode stages."""

    compact = compact_class(node)
    return "vaedecode" in compact or compact == "wanvideodecode"


def is_text_encode_node(node: PromptNode) -> bool:
    """Recognize prompt encoders and integrated conditioning providers."""

    compact = compact_class(node)
    if "textencode" in compact and "loader" not in compact:
        return True
    return compact in _INTEGRATED_PROMPT_PROVIDER_CLASSES or compact in (
        _DIRECT_IMAGE_GENERATOR_CLASSES
    )


def is_direct_image_generator_node(node: PromptNode) -> bool:
    """Return whether a node directly produces generated image pixels."""

    return compact_class(node) in _DIRECT_IMAGE_GENERATOR_CLASSES


def is_empty_latent_node(node: PromptNode) -> bool:
    """Recognize generated empty latent sources."""

    compact = compact_class(node)
    return "emptylatent" in compact or (compact.startswith("empty") and "latent" in compact)


def is_generated_latent_node(node: PromptNode) -> bool:
    """Recognize latent sources proven to start without input pixels."""

    if is_empty_latent_node(node):
        return True
    compact = compact_class(node)
    if compact in {
        "craspectratio",
        "craspectratiobanners",
        "craspectratioforprint",
        "craspectratiosocialmedia",
        "crsd15aspectratio",
        "crsdxlaspectratio",
        "wanvideoemptyembeds",
    }:
        return True
    source_inputs = (
        "image",
        "images",
        "input_image",
        "init_image",
        "fill_image",
        "mask",
        "video",
    )
    has_source_pixels = any(name in node.inputs for name in source_inputs)
    if compact in {"generatenoise", "imagenlatentepro", "latentnoisebatchperlin"}:
        return not has_source_pixels
    if compact == "smartresolutioncalc":
        return "vae" in node.inputs and not has_source_pixels
    return (
        "empty_latent_width" in node.inputs
        and "empty_latent_height" in node.inputs
        and not has_source_pixels
    )


def is_image_latent_node(node: PromptNode) -> bool:
    """Recognize graph evidence that pixels were encoded into latent space."""

    compact = compact_class(node)
    if compact == "smartresolutioncalc":
        return any(name in node.inputs for name in ("image", "fill_image", "mask"))
    if any(
        name in node.inputs
        for name in (
            "input_image",
            "init_image",
            "fill_image",
            "start_image",
            "end_image",
            "video",
        )
    ):
        return True
    return any(
        marker in compact
        for marker in (
            "vaeencode",
            "inpaintmodelconditioning",
            "latentfromimage",
            "encodeimage",
        )
    )


def is_image_source_node(node: PromptNode) -> bool:
    """Recognize current built-in image providers without guessing custom nodes."""

    return compact_class(node) in {"emptyimage", "loadimage", "loadimagemask"}


def is_primitive_node(node: PromptNode) -> bool:
    """Recognize scalar constants and reroutes used by linked widgets."""

    compact = compact_class(node)
    if compact in {"promptloramanager", "stringconstantmultiline"}:
        return True
    return any(
        marker in compact
        for marker in (
            "primitive",
            "constant",
            "reroute",
            "intvalue",
            "floatvalue",
            "stringvalue",
            "numbervalue",
        )
    )


@dataclass(frozen=True, slots=True)
class ResourceInputSpec:
    """One resource filename input with a stable role and kind."""

    input_name: str
    role: ResourceRole
    kind: ResourceKind
    rule_id: str


@dataclass(frozen=True, slots=True)
class FixedResourceSpec:
    """One source-backed fixed resource used by an input-less loader."""

    selected_value: str
    role: ResourceRole
    kind: ResourceKind
    rule_id: str


def _present(
    node: PromptNode,
    names: tuple[str, ...],
    role: ResourceRole,
    kind: ResourceKind,
    rule_id: str,
) -> tuple[ResourceInputSpec, ...]:
    return tuple(
        ResourceInputSpec(name, role, kind, rule_id) for name in names if name in node.inputs
    )


@dataclass(frozen=True, slots=True)
class _ExactResourceGroup:
    fields: tuple[str, ...]
    role: ResourceRole
    kind: ResourceKind


@dataclass(frozen=True, slots=True)
class _ExactResourceRule:
    rule_id: str
    class_types: frozenset[str]
    groups: tuple[_ExactResourceGroup, ...]


_INTEGRATED_TEXT_ENCODER_FIELDS = (
    "clip_name",
    "clip_name1",
    "clip_name2",
    "clip_name3",
    "clip_name4",
    "clip_name1_opt",
    "clip_name2_opt",
    "clip_name3_opt",
    "clip_name4_opt",
    "clip_l_name",
    "clip_g_name",
    "clip_name_l",
    "clip_name_g",
    "text_encoder_name",
    "t5_name",
    "gemma_path",
)
_INTEGRATED_PROMPT_PROVIDER_CLASSES = frozenset(
    {
        "crossattnerasereplacehidream",
        "crsdxlbasepromptencoder",
        "crencodescheduledprompts",
        "efficientloader",
        "efficientloadersdxl",
        "effloadersdxl",
        "easya1111loader",
        "easycascadeloader",
        "easycomfyloader",
        "easyfluxloader",
        "easyfullloader",
        "easyhunyuanditloader",
        "easykolorsloader",
        "easymochiloader",
        "easypixartloader",
        "easysv3dloader",
        "easysvdloader",
        "easyzero123loader",
        "easystylesselector",
        "easypipeedit",
        "easypipeeditprompt",
        "loadcheckpointtopipe",
        "loadcheckpointwithprompt",
        "ltxvmultipromptprovider",
        "multipromptprovider",
        "impactwildcardencode",
        "photomakerencode",
        "powerpromptrgthree",
        "powerpromptsimplergthree",
        "promptloramanager",
        "seargesdxlbasepromptencoder",
        "seargesdxlpromptencoder",
        "seargesdxlrefinerpromptencoder",
        "sdxlpowerpromptpositivergthree",
        "sdxlpowerpromptsimplenegativergthree",
        "step1xeditgenerate",
        "step1xeditteacachegenerate",
        "textparsea1111embeddings",
        "texttoconditioning",
        "sagezeroconditioning",
        "sagesinglecliptextimageencode",
        "ttnpipeloader",
        "ttnpipeloadersdxl",
        "ttnpipeloadersdxlv2",
        "ttnpipeloaderv2",
        "adepromptscheduling",
        "adepromptschedulinglatents",
        "wanvideotextencode",
        "wanvideotextencodecached",
        "wanvideotextencodecachedmultigpu",
        "wanvideotextencodemultigpu",
        "wanvideotextencodesingle",
        "wanvideotextencodesinglemultigpu",
    }
)
_EASY_INTEGRATED_LOADER_CLASSES = frozenset(
    item for item in _INTEGRATED_PROMPT_PROVIDER_CLASSES if item.startswith("easy")
)
_MULTIGPU_GGUF_UNET_CLASSES = frozenset(
    {
        "unetloaderggufadvanceddistorch2multigpu",
        "unetloaderggufadvanceddistorchmultigpu",
        "unetloaderggufadvancedmultigpu",
        "unetloaderggufdistorch2multigpu",
        "unetloaderggufdistorchmultigpu",
        "unetloaderggufmultigpu",
    }
)
_MULTIGPU_GGUF_CLIP_CLASSES = frozenset(
    {
        "cliploaderggufdistorch2multigpu",
        "cliploaderggufdistorchmultigpu",
        "cliploaderggufmultigpu",
        "dualcliploaderggufdistorch2multigpu",
        "dualcliploaderggufdistorchmultigpu",
        "dualcliploaderggufmultigpu",
        "quadruplecliploaderggufdistorch2multigpu",
        "quadruplecliploaderggufdistorchmultigpu",
        "quadruplecliploaderggufmultigpu",
        "triplecliploaderggufdistorch2multigpu",
        "triplecliploaderggufdistorchmultigpu",
        "triplecliploaderggufmultigpu",
    }
)
_EXACT_RESOURCE_RULES = (
    _ExactResourceRule(
        "hunyuan3d_model_loader",
        frozenset({"hy3dmodelloader"}),
        (
            _ExactResourceGroup(
                ("model",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
        ),
    ),
    _ExactResourceRule(
        "hunyuan3d_vae_loader",
        frozenset({"hy3dvaeloader"}),
        (
            _ExactResourceGroup(
                ("model_name",),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
        ),
    ),
    _ExactResourceRule(
        "sage_checkpoint_selector",
        frozenset({"sagecheckpointselector"}),
        (
            _ExactResourceGroup(
                ("ckpt_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.CHECKPOINT,
            ),
        ),
    ),
    _ExactResourceRule(
        "sage_unet_selector",
        frozenset({"sageunetselector"}),
        (
            _ExactResourceGroup(
                ("unet_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
        ),
    ),
    _ExactResourceRule(
        "sage_vae_selector",
        frozenset({"sagevaeselector"}),
        (
            _ExactResourceGroup(
                ("vae_name",),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
        ),
    ),
    _ExactResourceRule(
        "sage_clip_selector",
        frozenset(
            {
                "sageclipselector",
                "sagedualclipselector",
                "sagequadclipselector",
                "sagetripleclipselector",
            }
        ),
        (
            _ExactResourceGroup(
                ("clip_name", "clip_name_1", "clip_name_2", "clip_name_3", "clip_name_4"),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            ),
        ),
    ),
    _ExactResourceRule(
        "sage_multi_model_selector",
        frozenset(
            {
                "sagemultiselectordoubleclip",
                "sagemultiselectorquadclip",
                "sagemultiselectorsingleclip",
                "sagemultiselectortripleclip",
            }
        ),
        (
            _ExactResourceGroup(
                ("unet_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
            _ExactResourceGroup(
                ("clip_name", "clip_name_1", "clip_name_2", "clip_name_3", "clip_name_4"),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            ),
            _ExactResourceGroup(
                ("vae_name",),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
        ),
    ),
    _ExactResourceRule(
        "apt_ipadapter_apply",
        frozenset({"chxipaadv", "chxipafaceidadv"}),
        (
            _ExactResourceGroup(
                ("ipadapter_file",),
                ResourceRole.IPADAPTER,
                ResourceKind.IPADAPTER,
            ),
            _ExactResourceGroup(
                ("clip_vision",),
                ResourceRole.VISION_ENCODER,
                ResourceKind.VISION_ENCODER,
            ),
        ),
    ),
    _ExactResourceRule(
        "sdvn_style_model_apply",
        frozenset({"sdvnapplystylemodel"}),
        (
            _ExactResourceGroup(
                ("style_model",),
                ResourceRole.STYLE_MODEL,
                ResourceKind.STYLE_MODEL,
            ),
            _ExactResourceGroup(
                ("clip_vision_model",),
                ResourceRole.VISION_ENCODER,
                ResourceKind.VISION_ENCODER,
            ),
        ),
    ),
    _ExactResourceRule(
        "animatediff_motion_module",
        frozenset(
            {
                "adeanimatediffloadergen1",
                "adeanimatediffloaderwithcontext",
                "adeinjecti2vintoanimatediffmodel",
                "adeinjectpiaintoanimatediffmodel",
                "adeloadanimatelcmi2vmodel",
                "adeloadanimatediffmodel",
                "adeloadanimatediffmodelwithcameractrl",
            }
        ),
        (
            _ExactResourceGroup(
                ("model_name",),
                ResourceRole.MOTION_MODULE,
                ResourceKind.MOTION_MODULE,
            ),
        ),
    ),
    _ExactResourceRule(
        "animatediff_motionctrl_module",
        frozenset({"adeloadmotionctrlcmcmmodel", "adeloadmotionctrlomcmmodel"}),
        (
            _ExactResourceGroup(
                ("model_name", "motionctrl_cmcm", "motionctrl_omcm"),
                ResourceRole.MOTION_MODULE,
                ResourceKind.MOTION_MODULE,
            ),
        ),
    ),
    _ExactResourceRule(
        "core_style_model_loader",
        frozenset({"stylemodelloader"}),
        (
            _ExactResourceGroup(
                ("style_model_name",),
                ResourceRole.STYLE_MODEL,
                ResourceKind.STYLE_MODEL,
            ),
        ),
    ),
    _ExactResourceRule(
        "core_clip_vision_loader",
        frozenset({"clipvisionloader"}),
        (
            _ExactResourceGroup(
                ("clip_name",),
                ResourceRole.VISION_ENCODER,
                ResourceKind.VISION_ENCODER,
            ),
        ),
    ),
    _ExactResourceRule(
        "core_model_patch_loader",
        frozenset({"modelpatchloader"}),
        (
            _ExactResourceGroup(
                ("name",),
                ResourceRole.MODEL_PATCH,
                ResourceKind.MODEL_PATCH,
            ),
        ),
    ),
    _ExactResourceRule(
        "res4lyf_layer_patcher",
        frozenset({"layerpatcher"}),
        (
            _ExactResourceGroup(
                ("embedder", "gates", "last_layer"),
                ResourceRole.MODEL_PATCH,
                ResourceKind.MODEL_PATCH,
            ),
        ),
    ),
    _ExactResourceRule(
        "auxiliary_model_loader",
        frozenset(
            {
                "loadda3model",
                "loadmediapipefacelandmarker",
                "loadmogemodel",
                "loadnlfmodel",
                "samloader",
            }
        ),
        (
            _ExactResourceGroup(
                ("model_name", "nlf_model"),
                ResourceRole.AUXILIARY_MODEL,
                ResourceKind.AUXILIARY_MODEL,
            ),
        ),
    ),
    _ExactResourceRule(
        "wan_lynx_resampler_loader",
        frozenset({"loadlynxresampler"}),
        (
            _ExactResourceGroup(
                ("model_name",),
                ResourceRole.IPADAPTER,
                ResourceKind.IPADAPTER,
            ),
        ),
    ),
    _ExactResourceRule(
        "core_gligen_loader",
        frozenset({"gligenloader"}),
        (
            _ExactResourceGroup(
                ("gligen_name",),
                ResourceRole.GLIGEN,
                ResourceKind.GLIGEN,
            ),
        ),
    ),
    _ExactResourceRule(
        "core_hook_lora",
        frozenset({"createhooklora", "createhookloramodelonly"}),
        (
            _ExactResourceGroup(
                ("lora_name",),
                ResourceRole.LORA,
                ResourceKind.LORA,
            ),
        ),
    ),
    _ExactResourceRule(
        "core_hook_model_patch",
        frozenset({"createhookmodelaslora", "createhookmodelasloramodelonly"}),
        (
            _ExactResourceGroup(
                ("ckpt_name",),
                ResourceRole.MODEL_PATCH,
                ResourceKind.MODEL_PATCH,
            ),
        ),
    ),
    _ExactResourceRule(
        "multigpu_gguf_unet_loader",
        _MULTIGPU_GGUF_UNET_CLASSES,
        (
            _ExactResourceGroup(
                ("unet_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
        ),
    ),
    _ExactResourceRule(
        "multigpu_gguf_text_encoder_loader",
        _MULTIGPU_GGUF_CLIP_CLASSES,
        (
            _ExactResourceGroup(
                ("clip_name", "clip_name1", "clip_name2", "clip_name3", "clip_name4"),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            ),
        ),
    ),
    _ExactResourceRule(
        "wan_qwen_text_encoder_loader",
        frozenset({"qwenloader"}),
        (
            _ExactResourceGroup(
                ("model",),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            ),
        ),
    ),
    _ExactResourceRule(
        "core_hypernetwork_loader",
        frozenset({"hypernetworkloader"}),
        (
            _ExactResourceGroup(
                ("hypernetwork_name",),
                ResourceRole.HYPERNETWORK,
                ResourceKind.HYPERNETWORK,
            ),
        ),
    ),
    _ExactResourceRule(
        "vae_gguf_loader",
        frozenset({"vaegguf"}),
        (
            _ExactResourceGroup(
                ("vae_name", "gguf_name"),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
        ),
    ),
    _ExactResourceRule(
        "apt_gguf_loader",
        frozenset({"loadgguf"}),
        (
            _ExactResourceGroup(
                ("unet_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
        ),
    ),
    _ExactResourceRule(
        "diffusers_pipeline_loader",
        frozenset({"diffusersloader", "diffusersmodelloader"}),
        (
            _ExactResourceGroup(
                ("model_path",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
        ),
    ),
    _ExactResourceRule(
        "was_diffusers_hub_loader",
        frozenset({"diffusershubmodeldownloader"}),
        (
            _ExactResourceGroup(
                ("repo_id",),
                ResourceRole.BASE_MODEL,
                ResourceKind.EXTERNAL_MODEL,
            ),
        ),
    ),
    _ExactResourceRule(
        "step1x_edit_integrated_loader",
        frozenset(
            {
                "step1xeditmodelloader",
                "step1xeditteacachemodelloader",
            }
        ),
        (
            _ExactResourceGroup(
                ("diffusion_model",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
            _ExactResourceGroup(
                ("vae",),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
            _ExactResourceGroup(
                ("text_encoder",),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            ),
        ),
    ),
    _ExactResourceRule(
        "advanced_gguf_loader",
        frozenset({"loaderggufadvanced"}),
        (
            _ExactResourceGroup(
                ("gguf_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
        ),
    ),
    _ExactResourceRule(
        "gen2_qwen_vae_loader",
        frozenset({"gen2loadqwenvae"}),
        (
            _ExactResourceGroup(
                ("model_name",),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
        ),
    ),
    _ExactResourceRule(
        "a1r_checkpoint_loader",
        frozenset({"a1rcheckpointloader"}),
        (
            _ExactResourceGroup(
                ("ckpt_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.CHECKPOINT,
            ),
            _ExactResourceGroup(
                ("vae_name",),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
        ),
    ),
    _ExactResourceRule(
        "a1r_multi_checkpoint_loader",
        frozenset(
            {
                "a1rconditionalcheckpointloader",
                "a1rdoublecheckpointloader",
                "a1rseparatecheckpointloader",
            }
        ),
        (
            _ExactResourceGroup(
                ("ckpt_name_a", "ckpt_name_b"),
                ResourceRole.BASE_MODEL,
                ResourceKind.CHECKPOINT,
            ),
            _ExactResourceGroup(
                ("vae_name",),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
        ),
    ),
    _ExactResourceRule(
        "flux_trainer_integrated_model_select",
        frozenset({"fluxtrainmodelselect"}),
        (
            _ExactResourceGroup(
                ("transformer",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
            _ExactResourceGroup(
                ("vae",),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
            _ExactResourceGroup(
                ("clip_l", "t5"),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            ),
        ),
    ),
    _ExactResourceRule(
        "flux_trainer_inference_lora",
        frozenset({"fluxkohyainferencesampler"}),
        (
            _ExactResourceGroup(
                ("lora_name",),
                ResourceRole.LORA,
                ResourceKind.LORA,
            ),
        ),
    ),
    _ExactResourceRule(
        "withanyone_integrated_loader",
        frozenset({"withanyonemodelloadernode"}),
        (
            _ExactResourceGroup(
                ("flux_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
            _ExactResourceGroup(
                ("ipa_name",),
                ResourceRole.IPADAPTER,
                ResourceKind.IPADAPTER,
            ),
            _ExactResourceGroup(
                ("lora_name",),
                ResourceRole.LORA,
                ResourceKind.LORA,
            ),
        ),
    ),
    _ExactResourceRule(
        "zimage_integrated_loader",
        frozenset({"zimagemodelloader"}),
        (
            _ExactResourceGroup(
                ("model_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
            _ExactResourceGroup(
                ("vae_name",),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
            _ExactResourceGroup(
                ("clip_name",),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            ),
        ),
    ),
    _ExactResourceRule(
        "ltx_gemma_integrated_loader",
        frozenset({"ltxvgemmaclipmodelloader"}),
        (
            _ExactResourceGroup(
                ("ltxv_path",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
            _ExactResourceGroup(
                ("gemma_path",),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            ),
        ),
    ),
    _ExactResourceRule(
        "ltx_av_text_encoder_loader",
        frozenset({"ltxavtextencoderloader"}),
        (
            _ExactResourceGroup(
                ("ckpt_name",),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            ),
        ),
    ),
    _ExactResourceRule(
        "ltx_q8_lora_loader",
        frozenset({"ltxvq8loramodelloader"}),
        (
            _ExactResourceGroup(
                ("lora_name",),
                ResourceRole.LORA,
                ResourceKind.LORA,
            ),
        ),
    ),
    _ExactResourceRule(
        "integrated_diffusion_loader",
        frozenset(
            {
                "clownmodelloader",
                "diffusionmodelloaderkj",
                "fluxloader",
                "sd35loader",
            }
        ),
        (
            _ExactResourceGroup(
                ("model_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
            _ExactResourceGroup(
                _INTEGRATED_TEXT_ENCODER_FIELDS,
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            ),
            _ExactResourceGroup(
                ("vae_name",),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
        ),
    ),
    _ExactResourceRule(
        "checkpoint_pipe_loader",
        frozenset({"loadcheckpointtopipe", "loadcheckpointwithprompt"}),
        (
            _ExactResourceGroup(
                ("ckpt_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.CHECKPOINT,
            ),
        ),
    ),
    _ExactResourceRule(
        "efficiency_integrated_loader",
        frozenset({"efficientloader"}),
        (
            _ExactResourceGroup(
                ("ckpt_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.CHECKPOINT,
            ),
            _ExactResourceGroup(
                ("vae_name",),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
            _ExactResourceGroup(
                ("lora_name",),
                ResourceRole.LORA,
                ResourceKind.LORA,
            ),
        ),
    ),
    _ExactResourceRule(
        "efficiency_sdxl_integrated_loader",
        frozenset({"efficientloadersdxl", "effloadersdxl"}),
        (
            _ExactResourceGroup(
                ("base_ckpt_name", "refiner_ckpt_name"),
                ResourceRole.BASE_MODEL,
                ResourceKind.CHECKPOINT,
            ),
            _ExactResourceGroup(
                ("vae_name",),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
        ),
    ),
    _ExactResourceRule(
        "tinyterra_integrated_loader",
        frozenset(
            {
                "ttnpipeloader",
                "ttnpipeloadersdxl",
                "ttnpipeloadersdxlv2",
                "ttnpipeloaderv2",
            }
        ),
        (
            _ExactResourceGroup(
                ("ckpt_name", "base_ckpt_name", "refiner_ckpt_name"),
                ResourceRole.BASE_MODEL,
                ResourceKind.CHECKPOINT,
            ),
            _ExactResourceGroup(
                ("vae_name",),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
        ),
    ),
    _ExactResourceRule(
        "inspire_shared_diffusion_loader",
        frozenset({"loaddiffusionmodelsharedinspire"}),
        (
            _ExactResourceGroup(
                ("model_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
        ),
    ),
    _ExactResourceRule(
        "inspire_shared_text_encoder_loader",
        frozenset({"loadtextencodersharedinspire"}),
        (
            _ExactResourceGroup(
                ("model_name1", "model_name2", "model_name3"),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            ),
        ),
    ),
    _ExactResourceRule(
        "wan_text_encoder_loader",
        frozenset(
            {
                "loadwanvideot5textencoder",
                "loadwanvideot5textencodermultigpu",
                "wanvideotextencodecached",
            }
        ),
        (
            _ExactResourceGroup(
                ("model_name",),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            ),
        ),
    ),
    _ExactResourceRule(
        "nunchaku_text_encoder_loader",
        frozenset(
            {
                "nunchakutextencoderloader",
                "nunchakutextencoderloaderv2",
            }
        ),
        (
            _ExactResourceGroup(
                ("text_encoder1", "text_encoder2", "text_encoder3"),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            ),
        ),
    ),
    _ExactResourceRule(
        "nunchaku_diffusion_loader",
        frozenset(
            {
                "nunchakufluxditloader",
                "nunchakumodelloader",
                "nunchakuqwenimageditloader",
                "nunchakuzimageditloader",
            }
        ),
        (
            _ExactResourceGroup(
                ("model_path", "model_name"),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
        ),
    ),
    _ExactResourceRule(
        "nunchaku_pulid_loader",
        frozenset({"nunchakupulidloaderv2"}),
        (
            _ExactResourceGroup(
                ("pulid_file",),
                ResourceRole.IPADAPTER,
                ResourceKind.IPADAPTER,
            ),
        ),
    ),
    _ExactResourceRule(
        "pulid_adapter_loader",
        frozenset(
            {
                "pulidfluxmodelloader",
                "pulidmodelloader",
                "pulidmodelloadermultigpu",
            }
        ),
        (
            _ExactResourceGroup(
                ("pulid_file",),
                ResourceRole.IPADAPTER,
                ResourceKind.IPADAPTER,
            ),
        ),
    ),
    _ExactResourceRule(
        "easy_control_adapter_loader",
        frozenset({"easyllliteloader"}),
        (
            _ExactResourceGroup(
                ("model_name",),
                ResourceRole.CONTROLNET,
                ResourceKind.CONTROLNET,
            ),
        ),
    ),
    _ExactResourceRule(
        "easy_pulid_adapter",
        frozenset({"easypulidapply", "easypulidapplyadv"}),
        (
            _ExactResourceGroup(
                ("pulid_file",),
                ResourceRole.IPADAPTER,
                ResourceKind.IPADAPTER,
            ),
        ),
    ),
    _ExactResourceRule(
        "easy_cascade_vae",
        frozenset({"easyfullcascadeksampler"}),
        (
            _ExactResourceGroup(
                ("encode_vae_name", "decode_vae_name"),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
        ),
    ),
    _ExactResourceRule(
        "easy_upscaler",
        frozenset({"easyhiresfix"}),
        (
            _ExactResourceGroup(
                ("model_name",),
                ResourceRole.UPSCALER,
                ResourceKind.UPSCALER,
            ),
        ),
    ),
    _ExactResourceRule(
        "comfyroll_upscaler",
        frozenset({"crupscaleimage"}),
        (
            _ExactResourceGroup(
                ("upscale_model",),
                ResourceRole.UPSCALER,
                ResourceKind.UPSCALER,
            ),
        ),
    ),
    _ExactResourceRule(
        "wan_diffusion_loader",
        frozenset({"wanvideomodelloader", "wanvideomodelloadermultigpu"}),
        (
            _ExactResourceGroup(
                ("model",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
        ),
    ),
    _ExactResourceRule(
        "wan_extra_diffusion_selector",
        frozenset({"wanvideoextramodelselect", "wanvideovacemodelselect"}),
        (
            _ExactResourceGroup(
                ("extra_model", "vace_model"),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
        ),
    ),
    _ExactResourceRule(
        "wan_lora_selector",
        frozenset({"wanvideoloraselect", "wanvideoloraselectbyname"}),
        (
            _ExactResourceGroup(
                ("lora", "lora_name"),
                ResourceRole.LORA,
                ResourceKind.LORA,
            ),
        ),
    ),
    _ExactResourceRule(
        "wan_controlnet_loader",
        frozenset({"wanvideocontrolnetloader", "wanvideouni3ccontrolnetloader"}),
        (
            _ExactResourceGroup(
                ("model",),
                ResourceRole.CONTROLNET,
                ResourceKind.CONTROLNET,
            ),
        ),
    ),
    _ExactResourceRule(
        "wan_vae_loader",
        frozenset({"wanvideoflashvsrdecoderloader", "wanvideotinyvaeloader"}),
        (
            _ExactResourceGroup(
                ("model_name",),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
        ),
    ),
    _ExactResourceRule(
        "source_backed_checkpoint_loader",
        frozenset(
            {
                "blenderinputloadcheckpoint",
                "quantizedmodelloader",
                "quantizedmodelloadersimple",
            }
        ),
        (
            _ExactResourceGroup(
                ("ckpt_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.CHECKPOINT,
            ),
        ),
    ),
    _ExactResourceRule(
        "source_backed_diffusion_loader",
        frozenset(
            {
                "blenderinputloaddiffusionmodel",
                "d2loaddiffusionmodel",
                "d2loaddiffusionmodelset",
                "enhancedloaddiffusionmodel",
                "velocatorloadandquantizediffusionmodel",
            }
        ),
        (
            _ExactResourceGroup(
                ("unet_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
            ),
            _ExactResourceGroup(
                ("vae_name",),
                ResourceRole.VAE,
                ResourceKind.VAE,
            ),
            _ExactResourceGroup(
                ("clip_name",),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            ),
        ),
    ),
    _ExactResourceRule(
        "wavespeed_quantized_text_encoder_loader",
        frozenset({"velocatorloadandquantizeclip"}),
        (
            _ExactResourceGroup(
                ("clip_name1", "clip_name2", "clip_name3"),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            ),
        ),
    ),
)


def _exact_resource_specs(
    node: PromptNode,
    compact: str,
) -> tuple[ResourceInputSpec, ...]:
    for rule in _EXACT_RESOURCE_RULES:
        if compact not in rule.class_types:
            continue
        return tuple(
            spec
            for group in rule.groups
            for spec in _present(
                node,
                group.fields,
                group.role,
                group.kind,
                rule.rule_id,
            )
        )
    return ()


def _is_linked(node: PromptNode, input_name: str) -> bool:
    return as_link_reference(node.input_value(input_name)) is not None


def _easy_loader_specs(
    node: PromptNode,
    compact: str,
) -> tuple[ResourceInputSpec, ...]:
    if compact not in _EASY_INTEGRATED_LOADER_CLASSES:
        return ()
    specs: list[ResourceInputSpec] = []
    if not _is_linked(node, "model_override"):
        specs.extend(
            _present(
                node,
                ("ckpt_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.CHECKPOINT,
                "easy_integrated_loader",
            )
        )
        specs.extend(
            _present(
                node,
                ("model_name", "unet_name", "stage_c", "stage_b"),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
                "easy_integrated_loader",
            )
        )
    if not _is_linked(node, "clip_override"):
        specs.extend(
            _present(
                node,
                (*_INTEGRATED_TEXT_ENCODER_FIELDS, "chatglm3_name"),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
                "easy_integrated_loader",
            )
        )
    if not _is_linked(node, "vae_override"):
        specs.extend(
            _present(
                node,
                ("vae_name", "stage_a"),
                ResourceRole.VAE,
                ResourceKind.VAE,
                "easy_integrated_loader",
            )
        )
    specs.extend(
        _present(
            node,
            ("lora_name",),
            ResourceRole.LORA,
            ResourceKind.LORA,
            "easy_integrated_loader",
        )
    )
    return tuple(specs)


def _selected_resource_specs(
    node: PromptNode,
    compact: str,
) -> tuple[ResourceInputSpec, ...]:
    if compact.startswith("cr"):
        return _comfyroll_selected_resource_specs(node, compact)
    if compact == "easyloraswitcher":
        return _easy_selected_lora_specs(node)
    if compact == "lfdiffusionmodelselector":
        return _lf_diffusion_model_specs(node)
    if compact == "modelassembler":
        return _model_assembler_specs(node)
    return _researched_selected_resource_specs(node, compact)


def _researched_selected_resource_specs(
    node: PromptNode,
    compact: str,
) -> tuple[ResourceInputSpec, ...]:
    if compact in {"h4completeloader", "h4universalloader"}:
        return _h4_loader_specs(node)
    if compact in {"loadnanchaku", "sumloadadv"}:
        return _apt_integrated_loader_specs(node, compact)
    if compact in {"sdvnloadcheckpoint", "sdvnloadcheckpointfilter"}:
        return _sdvn_checkpoint_specs(node)
    return ()


def _lf_diffusion_model_specs(node: PromptNode) -> tuple[ResourceInputSpec, ...]:
    randomize = node.input_value("randomize")
    if randomize is True or (isinstance(randomize, str) and randomize.strip().casefold() == "true"):
        return ()
    return _present(
        node,
        ("diffusion_model",),
        ResourceRole.BASE_MODEL,
        ResourceKind.DIFFUSION_MODEL,
        "lf_diffusion_model_loader",
    )


def _model_assembler_specs(node: PromptNode) -> tuple[ResourceInputSpec, ...]:
    mode = node.input_value("load_mode")
    if not isinstance(mode, str):
        return ()
    if mode.strip().casefold() == "full_checkpoint":
        return _present(
            node,
            ("ckpt_name",),
            ResourceRole.BASE_MODEL,
            ResourceKind.CHECKPOINT,
            "model_assembler_checkpoint",
        )
    if mode.strip().casefold() != "separate_components":
        return ()
    return (
        *_present(
            node,
            ("base_model",),
            ResourceRole.BASE_MODEL,
            ResourceKind.DIFFUSION_MODEL,
            "model_assembler_components",
        ),
        *_present(
            node,
            ("vae_model",),
            ResourceRole.VAE,
            ResourceKind.VAE,
            "model_assembler_components",
        ),
        *_present(
            node,
            ("clip_model_1", "clip_model_2", "clip_model_3"),
            ResourceRole.TEXT_ENCODER,
            ResourceKind.CLIP,
            "model_assembler_components",
        ),
    )


def _h4_loader_specs(node: PromptNode) -> tuple[ResourceInputSpec, ...]:
    mode = node.input_value("load_mode")
    if not isinstance(mode, str):
        return ()
    normalized = mode.strip().casefold()
    if normalized == "checkpoint (standard)":
        model_specs = _present(
            node,
            ("ckpt_name",),
            ResourceRole.BASE_MODEL,
            ResourceKind.CHECKPOINT,
            "h4_integrated_checkpoint_loader",
        )
    elif normalized == "diffusers (component)":
        model_specs = (
            *_present(
                node,
                ("unet_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
                "h4_integrated_component_loader",
            ),
            *_present(
                node,
                ("clip_name",),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
                "h4_integrated_component_loader",
            ),
            *_present(
                node,
                ("vae_name",),
                ResourceRole.VAE,
                ResourceKind.VAE,
                "h4_integrated_component_loader",
            ),
        )
    else:
        return ()
    return (
        *model_specs,
        *_present(
            node,
            ("lora_name",),
            ResourceRole.LORA,
            ResourceKind.LORA,
            "h4_integrated_lora_loader",
        ),
    )


def _apt_integrated_loader_specs(
    node: PromptNode,
    compact: str,
) -> tuple[ResourceInputSpec, ...]:
    specs: list[ResourceInputSpec] = []
    if not _is_linked(node, "over_model"):
        if compact == "sumloadadv":
            specs.extend(
                _present(
                    node,
                    ("ckpt_name",),
                    ResourceRole.BASE_MODEL,
                    ResourceKind.CHECKPOINT,
                    "apt_integrated_checkpoint_loader",
                )
            )
        specs.extend(
            _present(
                node,
                ("unet_name",),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
                "apt_integrated_diffusion_loader",
            )
        )
    if not _is_linked(node, "over_clip"):
        specs.extend(
            _present(
                node,
                ("clip1", "clip2", "clip3", "clip4"),
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
                "apt_integrated_text_encoder_loader",
            )
        )
    specs.extend(
        _present(
            node,
            ("vae",),
            ResourceRole.VAE,
            ResourceKind.VAE,
            "apt_integrated_vae_loader",
        )
    )
    specs.extend(
        _present(
            node,
            ("lora",),
            ResourceRole.LORA,
            ResourceKind.LORA,
            "apt_integrated_lora_loader",
        )
    )
    return tuple(specs)


def _sdvn_checkpoint_specs(node: PromptNode) -> tuple[ResourceInputSpec, ...]:
    download = node.input_value("Download")
    download_url = node.input_value("Download_url")
    use_download_name = (
        download is True and isinstance(download_url, str) and bool(download_url.strip())
    )
    return _present(
        node,
        ("Ckpt_url_name" if use_download_name else "Ckpt_name",),
        ResourceRole.BASE_MODEL,
        ResourceKind.CHECKPOINT,
        "sdvn_effective_checkpoint_loader",
    )


def _comfyroll_selected_resource_specs(
    node: PromptNode,
    compact: str,
) -> tuple[ResourceInputSpec, ...]:
    result: tuple[ResourceInputSpec, ...] = ()
    if compact == "crselectmodel":
        selected = node.input_value("select_model")
        if (
            isinstance(selected, int)
            and not isinstance(selected, bool)
            and 1 <= selected <= _COMFYROLL_MODEL_SLOT_COUNT
        ):
            result = _present(
                node,
                (f"ckpt_name{selected}",),
                ResourceRole.BASE_MODEL,
                ResourceKind.CHECKPOINT,
                "comfyroll_selected_model",
            )
    elif compact == "crloadscheduledmodels":
        mode = node.input_value("mode")
        if isinstance(mode, str) and mode.strip().casefold() == "load default model":
            result = _present(
                node,
                ("default_model",),
                ResourceRole.BASE_MODEL,
                ResourceKind.CHECKPOINT,
                "comfyroll_default_scheduled_model",
            )
    elif compact == "crloadscheduledloras":
        mode = node.input_value("mode")
        if isinstance(mode, str) and mode.strip().casefold() == "load default lora":
            result = _present(
                node,
                ("default_lora",),
                ResourceRole.LORA,
                ResourceKind.LORA,
                "comfyroll_default_scheduled_lora",
            )
    elif compact == "crmodelmergestack":
        for index in range(1, 4):
            switch = node.input_value(f"switch_{index}")
            if isinstance(switch, str) and switch.strip().casefold() == "on":
                result += _present(
                    node,
                    (f"ckpt_name{index}",),
                    ResourceRole.BASE_MODEL,
                    ResourceKind.CHECKPOINT,
                    "comfyroll_model_merge_stack",
                )
    return result


def _easy_selected_lora_specs(node: PromptNode) -> tuple[ResourceInputSpec, ...]:
    if node.input_value("toggle") is False:
        return ()
    selected = node.input_value("select")
    if (
        not isinstance(selected, int)
        or isinstance(selected, bool)
        or not 1 <= selected <= _EASY_LORA_SLOT_COUNT
    ):
        return ()
    return _present(
        node,
        (f"lora_{selected}_name",),
        ResourceRole.LORA,
        ResourceKind.LORA,
        "easy_selected_lora",
    )


def _easy_adapter_specs(
    node: PromptNode,
    compact: str,
) -> tuple[ResourceInputSpec, ...]:
    if compact not in {"easyinstantidapply", "easyinstantidapplyadv"}:
        return ()
    specs = list(
        _present(
            node,
            ("instantid_file",),
            ResourceRole.IPADAPTER,
            ResourceKind.IPADAPTER,
            "easy_instantid_adapter",
        )
    )
    if not _is_linked(node, "control_net"):
        specs.extend(
            _present(
                node,
                ("control_net_name",),
                ResourceRole.CONTROLNET,
                ResourceKind.CONTROLNET,
                "easy_instantid_controlnet",
            )
        )
    return tuple(specs)


def _gguf_kj_specs(node: PromptNode, compact: str) -> tuple[ResourceInputSpec, ...]:
    if compact != "ggufloaderkj":
        return ()
    specs = list(
        _present(
            node,
            ("model_name",),
            ResourceRole.BASE_MODEL,
            ResourceKind.DIFFUSION_MODEL,
            "kj_gguf_loader",
        )
    )
    extra = node.input_value("extra_model_name")
    role = (
        ResourceRole.TEXT_ENCODER
        if isinstance(extra, str) and "connector" in extra.casefold()
        else ResourceRole.BASE_MODEL
    )
    kind = ResourceKind.CLIP if role is ResourceRole.TEXT_ENCODER else ResourceKind.DIFFUSION_MODEL
    specs.extend(
        _present(
            node,
            ("extra_model_name",),
            role,
            kind,
            "kj_gguf_extra_model",
        )
    )
    return tuple(specs)


def _deduplicate_specs(
    specs: tuple[ResourceInputSpec, ...],
) -> tuple[ResourceInputSpec, ...]:
    result: list[ResourceInputSpec] = []
    seen: set[tuple[str, ResourceRole, ResourceKind]] = set()
    for spec in specs:
        identity = (spec.input_name, spec.role, spec.kind)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(spec)
    return tuple(result)


def resource_input_specs(node: PromptNode) -> tuple[ResourceInputSpec, ...]:
    """Return high-confidence filename inputs for current common node families."""

    compact = compact_class(node)
    specs: list[ResourceInputSpec] = []
    if "powerloraloader" in compact:
        return ()

    specs.extend(_selected_resource_specs(node, compact))
    specs.extend(_easy_adapter_specs(node, compact))
    specs.extend(_easy_loader_specs(node, compact))
    specs.extend(_gguf_kj_specs(node, compact))
    specs.extend(_exact_resource_specs(node, compact))

    if "loraloader" in compact or "loadlora" in compact:
        specs.extend(
            _present(
                node,
                ("lora_name", "lora", "model_name", "default_lora", "lora_path_opt"),
                ResourceRole.LORA,
                ResourceKind.LORA,
                "lora_loader_family",
            )
        )
    if "checkpointloader" in compact or ("checkpoint" in compact and compact.startswith("load")):
        specs.extend(
            _present(
                node,
                ("ckpt_name", "checkpoint", "checkpoint_name", "model_name", "model"),
                ResourceRole.BASE_MODEL,
                ResourceKind.CHECKPOINT,
                "checkpoint_loader_family",
            )
        )
    if (
        "unetloader" in compact
        or "diffusionmodelloader" in compact
        or compact.startswith("loaddiffusionmodel")
        or (
            "gguf" in compact
            and "loader" in compact
            and any(
                name in node.inputs
                for name in (
                    "unet_name",
                    "model_name",
                    "ckpt_name",
                    "gguf_name",
                    "diffusion_model_name",
                )
            )
        )
    ):
        specs.extend(
            _present(
                node,
                (
                    "unet_name",
                    "model_name",
                    "ckpt_name",
                    "gguf_name",
                    "diffusion_model_name",
                ),
                ResourceRole.BASE_MODEL,
                ResourceKind.DIFFUSION_MODEL,
                "diffusion_loader_family",
            )
        )
    if any(marker in compact for marker in ("vaeloader", "loadvae", "loadvaemodel", "loadvqvae")):
        specs.extend(
            _present(
                node,
                ("vae_name", "model_name", "ckpt_name"),
                ResourceRole.VAE,
                ResourceKind.VAE,
                "vae_loader_family",
            )
        )
    if (
        ("cliploader" in compact and "clipvisionloader" not in compact)
        or "textencoderloader" in compact
        or ("textencoder" in compact and compact.startswith("load"))
    ):
        names = tuple(
            name
            for name in node.inputs
            if name.startswith(("clip_name", "text_encoder_name", "model_name"))
            or name
            in {
                "gemma_path",
                "t5_name",
                "text_encoder1",
                "text_encoder2",
                "text_encoder3",
            }
        )
        specs.extend(
            _present(
                node,
                names,
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
                "text_encoder_loader_family",
            )
        )
    if "controlnetloader" in compact or ("brushnet" in compact and "loader" in compact):
        specs.extend(
            _present(
                node,
                (
                    "control_net_name",
                    "controlnet_name",
                    "controlnet",
                    "brushnet_name",
                    "model_name",
                ),
                ResourceRole.CONTROLNET,
                ResourceKind.CONTROLNET,
                "control_model_loader_family",
            )
        )
    if "ipadapter" in compact and "loader" in compact:
        specs.extend(
            _present(
                node,
                ("ipadapter_file", "ipadapter_name", "ipadapter", "model_name"),
                ResourceRole.IPADAPTER,
                ResourceKind.IPADAPTER,
                "ipadapter_loader_family",
            )
        )
    if "upscale" in compact and "loader" in compact:
        specs.extend(
            _present(
                node,
                ("model_name", "upscale_model_name", "upscaler_name", "upscale_model"),
                ResourceRole.UPSCALER,
                ResourceKind.UPSCALER,
                "upscaler_loader_family",
            )
        )
    if "embedding" in compact and "loader" in compact:
        specs.extend(
            _present(
                node,
                ("embedding_name", "embedding", "model_name"),
                ResourceRole.EMBEDDING,
                ResourceKind.EMBEDDING,
                "embedding_loader_family",
            )
        )
    return _deduplicate_specs(tuple(specs))


def fixed_resource_specs(node: PromptNode) -> tuple[FixedResourceSpec, ...]:
    """Return fixed files verified from a specific loader's source."""

    if compact_class(node) != "pulidfluxevacliploader":
        return ()
    return (
        FixedResourceSpec(
            selected_value="EVA02_CLIP_L_336_psz14_s6B.pt",
            role=ResourceRole.VISION_ENCODER,
            kind=ResourceKind.VISION_ENCODER,
            rule_id="pulid_flux_eva_clip_fixed",
        ),
    )


def is_base_model_loader(node: PromptNode) -> bool:
    """Return whether a node exposes a high-confidence base model resource."""

    return any(spec.role is ResourceRole.BASE_MODEL for spec in resource_input_specs(node))


def is_known_active_node(node: PromptNode) -> bool:
    """Return whether the scanner recognizes an active node's broad function."""

    if (
        is_sampler_node(node)
        or is_decode_node(node)
        or is_text_encode_node(node)
        or is_generated_latent_node(node)
        or is_image_latent_node(node)
        or is_image_source_node(node)
        or is_primitive_node(node)
        or bool(resource_input_specs(node))
        or bool(fixed_resource_specs(node))
    ):
        return True
    compact = compact_class(node)
    if compact in (
        _KNOWN_SAMPLER_PROVIDER_CLASSES
        | _KNOWN_REVIEWED_NON_RESOURCE_CLASSES
        | _SPECIAL_RESOURCE_CLASSES
    ):
        return True
    if "sigma" in compact and any("sigma" in input_name.casefold() for input_name in node.inputs):
        return True
    if compact in _MULTIGPU_GGUF_UNET_CLASSES | _MULTIGPU_GGUF_CLIP_CLASSES:
        return True
    if compact in {
        "busnode",
        "buspipe",
        "ccollinsciviscribesaveimage",
        "clipsetlastlayer",
        "clownoptionsswapsamplerbeta",
        "cmsdxlextendedresolution",
        "cmsdxlresolution",
        "combineregionalprompts",
        "contextbigrgthree",
        "contextmergebigrgthree",
        "contextmergergthree",
        "contextrgthree",
        "crapplymodelmerge",
        "crcombineprompt",
        "crcyclemodels",
        "crloadscheduledmodels",
        "crmodellist",
        "crmodelmergestack",
        "crmultilinetext",
        "crprompttext",
        "crselectmodel",
        "crtext",
        "crtextconcatenate",
        "crtextreplace",
        "dimensionselectorwithseednode",
        "detaildaemongraphsigmasnode",
        "diffusionmodelselector",
        "easyxyinputscheckpoint",
        "easystylesselector",
        "easyprompt",
        "easypromptconcat",
        "easypromptreplace",
        "extendintermediatesigmas",
        "frameinterpolationmodelloader",
        "hidreamo1referenceimages",
        "ideogram4promptbuilderkj",
        "impactstringselector",
        "lyingsigmasampler",
        "ovimmaudiovaeloader",
        "promptmultiplestylesselector",
        "promptstylesselector",
        "previewany",
        "referencelatent",
        "regionalprompt",
        "resolutionselector",
        "loadcache",
        "reloadimage",
        "reloadlatent",
        "reloadmodel",
        "selectordeimagenes",
        "selectordeprompts",
        "setcliphooks",
        "setimagesize",
        "setimagesizewithscale",
        "sigmasconwaysequence",
        "sigmasgilbreathsequence",
        "sigmasharmonicdecay",
        "sigmaslangevindynamics",
        "sigmasnormalizingflows",
        "sigmaspersistenthomology",
        "sigmasriemannianflow",
        "sigmasschedulepreview",
        "sigmasstepwisemultirate",
        "smartresolutioncalc",
        "stylemodelapply",
        "stylemodelapplyadvanced",
        "stylemodelapplystyle",
        "stringconcatenate",
        "t5tokenizeroptions",
        "tencentimagetomodelnode",
        "textbox1",
        "textbox2",
        "textparsea1111embeddings",
        "tobasicpipe",
        "usostylereference",
        "voidwarpednoise",
        "wanvideopromptextender",
        "wanvideopromptextenderselect",
        "gligentextboxapply",
        "gligentextboxapplybatchcoords",
    }:
        return True
    return any(
        marker in compact
        for marker in (
            "conditioning",
            "guidance",
            "guider",
            "scheduler",
            "samplerselect",
            "samplerprovider",
            "samplersettings",
            "noise",
            "modelsampling",
            "lora",
            "controlnet",
            "ipadapter",
            "upscale",
            "reroute",
            "switch",
        )
    )


__all__ = [
    "FixedResourceSpec",
    "ResourceInputSpec",
    "compact_class",
    "fixed_resource_specs",
    "is_antrobots_refiner_node",
    "is_antrobots_refiner_pipe_node",
    "is_base_model_loader",
    "is_decode_node",
    "is_direct_image_generator_node",
    "is_empty_latent_node",
    "is_generated_latent_node",
    "is_image_latent_node",
    "is_image_source_node",
    "is_known_active_node",
    "is_primitive_node",
    "is_sampler_node",
    "is_text_encode_node",
    "resource_input_specs",
]
