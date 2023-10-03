# Dear Bindings Version 0.07 WIP
# Generates C-language headers for Dear ImGui
# Developed by Ben Carter (e-mail: ben AT shironekolabs.com, github: @ShironekoBen)

# Example command-line:
#   python dear_bindings.py --output cimgui ../imgui/imgui.h
#   python dear_bindings.py --output cimgui_internal ../imgui/imgui_internal.h   (FIXME: result won't compile yet)

# Example Input:
#   imgui.h     : a C++ header file (aiming to also support imgui_internal.h, implot.h etc.: support is not complete yet).

# Example output:
#   cimgui.h    : a C header file for compilation by a modern C compiler, including full comments from original header file.
#   cimgui.cpp  : a CPP implementation file which can to be linked into a C program.
#   cimgui.json : full metadata to reconstruct bindings for other programming languages, including full comments.

import os
from src import code_dom
from src import c_lexer
from src import utils
import argparse
import sys
import traceback
from src.modifiers import *
from src.generators import *
from src.type_comprehension import *


# Insert a single header template file, complaining if it does not exist
# Replaces any expansions in the expansions dictionary with the given result
def insert_single_template(dest_file, template_file, expansions):
    if not os.path.isfile(template_file):
        print("Template file " + template_file + " could not be found (note that template file names are "
                                                 "expected to match source file names, so if you have "
                                                 "renamed imgui.h you will need to rename the template as "
                                                 "well). The common template file is included regardless of source "
                                                 "file name.")
        sys.exit(2)

    with open(template_file, "r") as src_file:
        for line in src_file.readlines():
            for before, after in expansions.items():
                line = line.replace(before, after)
            dest_file.write(line)


# Insert the contents of the appropriate header template file(s)
def insert_header_templates(dest_file, template_dir, src_file_name, dest_file_ext, expansions):
    # Include the common template file
    insert_single_template(dest_file,
                           os.path.join(template_dir, "common-header-template" + dest_file_ext),
                           expansions)

    # Include the specific template for the file we are generating
    insert_single_template(dest_file,
                           os.path.join(template_dir, src_file_name + "-header-template" + dest_file_ext),
                           expansions)


def parse_single_header(src_file, context):
    print("Parsing " + src_file)

    with open(src_file, "r") as f:
        file_content = f.read()

    # Tokenize file and then convert into a DOM

    stream = c_lexer.tokenize(file_content)

    if False:  # Debug dump tokens
        while True:
            tok = stream.get_token()
            if not tok:
                break  # No more input
            print(tok)
        return

    return code_dom.DOMHeaderFile.parse(context, stream, os.path.split(src_file)[1])


# Parse the C++ header found in src_file, and write a C header to dest_file_no_ext.h, with binding implementation in
# dest_file_no_ext.cpp. Metadata will be written to dest_file_no_ext.json. implementation_header should point to a file
# containing the initial header block for the implementation (provided in the templates/ directory).
def convert_header(
        src_file,
        config_include_files,
        dest_file_no_ext,
        template_dir,
        no_struct_by_value_arguments,
        no_generate_default_arg_functions,
        generate_exploded_varargs_functions,
        generate_unformatted_functions,
        is_backend,
        imgui_include_dir
    ):

    # Set up context and DOM root
    context = code_dom.ParseContext()
    dom_root = code_dom.DOMHeaderFileSet()

    # Parse any configuration include files and add them to the DOM
    for include_file in config_include_files:
        dom_root.add_child(parse_single_header(include_file, context))

    # Parse and add the main header
    main_src_root = parse_single_header(src_file, context)
    dom_root.add_child(main_src_root)

    # Assign a destination filename based on the output file
    _, main_src_root.dest_filename = os.path.split(dest_file_no_ext)
    main_src_root.dest_filename += ".h"  # Presume the primary output file is the .h

    # Check if we'll do some special treatment for imgui_internal.h
    dest_file_name_only = os.path.basename(dest_file_no_ext)
    is_probably_imgui_internal = dest_file_name_only.endswith('_internal')

    dom_root.validate_hierarchy()
    #  dom_root.dump()

    print("Storing unmodified DOM")

    dom_root.save_unmodified_clones()

    print("Applying modifiers")

    # Apply modifiers

    # Add headers we need and remove those we don't
    if not is_backend:
        mod_add_includes.apply(dom_root, ["<stdbool.h>"])  # We need stdbool.h to get bool defined
        mod_add_includes.apply(dom_root, ["<stdint.h>"])  # We need stdint.h to get int32_t
        mod_remove_includes.apply(dom_root, ["<float.h>",
                                             "<string.h>"])

    if is_backend:
        # Backends need to reference cimgui.h, not imgui.h
        mod_change_includes.apply(dom_root, {"\"imgui.h\"": "\"cimgui.h\""})

        # Backends need a forward-declaration for ImDrawData so that the code generator understands
        # that it is an ImGui type and needs conversion
        mod_add_forward_declarations.apply(dom_root, ["struct ImDrawData;"])

    mod_attach_preceding_comments.apply(dom_root)
    mod_remove_function_bodies.apply(dom_root)
    mod_assign_anonymous_type_names.apply(dom_root)
    # Remove ImGuiOnceUponAFrame for now as it needs custom fiddling to make it usable from C
    # Remove ImNewDummy/ImNewWrapper as it's a helper for C++ new (and C dislikes empty structs)
    mod_remove_structs.apply(dom_root, ["ImGuiOnceUponAFrame",
                                        "ImNewDummy",  # ImGui <1.82
                                        "ImNewWrapper",  # ImGui >=1.82
                                        # Templated stuff in imgui_internal.h
                                        "ImBitArray",
                                        "ImBitVector",
                                        "ImSpanAllocator",
                                        "ImChunkStream",
                                        "ImGuiTextIndex"])
    # Remove all functions from ImVector and ImSpan, as they're not really useful
    mod_remove_all_functions_from_classes.apply(dom_root, ["ImVector", "ImSpan"])
    # Remove all functions from ImPool, since we can't handle nested template functions yet
    mod_remove_all_functions_from_classes.apply(dom_root, ["ImPool"])
    # Remove Value() functions which are dumb helpers over Text(), would need custom names otherwise
    mod_remove_functions.apply(dom_root, ["ImGui::Value"])
    # Remove ImQsort() functions as modifiers on function pointers seem to emit a "anachronism used: modifiers on data are ignored" warning.
    mod_remove_functions.apply(dom_root, ["ImQsort"])
    # FIXME: Remove incorrectly parsed constructor due to "explicit" keyword.
    mod_remove_functions.apply(dom_root, ["ImVec2ih::ImVec2ih"])
    # Remove some templated functions from imgui_internal.h that we don't want and cause trouble
    mod_remove_functions.apply(dom_root, ["ImGui::ScaleRatioFromValueT",
                                          "ImGui::ScaleValueFromRatioT",
                                          "ImGui::DragBehaviorT",
                                          "ImGui::SliderBehaviorT",
                                          "ImGui::RoundScalarWithFormatT",
                                          "ImGui::CheckboxFlagsT"])

    mod_add_prefix_to_loose_functions.apply(dom_root, "c")

    if not is_backend:
        # Add helper functions to create/destroy ImVectors
        # Implementation code for these can be found in templates/imgui-header.cpp
        mod_add_manual_helper_functions.apply(dom_root,
                                              [
                                                  "void ImVector_Construct(void* vector); // Construct a "
                                                  "zero-size ImVector<> (of any type). This is primarily "
                                                  "useful when calling "
                                                  "ImFontGlyphRangesBuilder_BuildRanges()",

                                                  "void ImVector_Destruct(void* vector); // Destruct an "
                                                  "ImVector<> (of any type). Important: Frees the vector "
                                                  "memory but does not call destructors on contained objects "
                                                  "(if they have them)",
                                              ])
        # ImStr conversion helper, only enabled if IMGUI_HAS_IMSTR is on
        mod_add_manual_helper_functions.apply(dom_root,
                                              [
                                                  "ImStr ImStr_FromCharStr(const char* b); // Build an ImStr "
                                                  "from a regular const char* (no data is copied, so you need to make "
                                                  "sure the original char* isn't altered as long as you are using the "
                                                  "ImStr)."
                                              ],
                                              # This weirdness is because we want this to compile cleanly even if
                                              # IMGUI_HAS_IMSTR wasn't defined
                                              ["defined(IMGUI_HAS_IMSTR)", "IMGUI_HAS_IMSTR"])

    # Add a note to ImFontGlyphRangesBuilder_BuildRanges() pointing people at the helpers
    mod_add_function_comment.apply(dom_root,
                                   "ImFontGlyphRangesBuilder::BuildRanges",
                                   "(ImVector_Construct()/ImVector_Destruct() can be used to safely "
                                   "construct out_ranges)")

    mod_remove_operators.apply(dom_root)
    mod_remove_heap_constructors_and_destructors.apply(dom_root)
    mod_convert_references_to_pointers.apply(dom_root)
    if no_struct_by_value_arguments:
        mod_convert_by_value_struct_args_to_pointers.apply(dom_root)
    # Assume IM_VEC2_CLASS_EXTRA and IM_VEC4_CLASS_EXTRA are never defined as they are likely to just cause problems
    # if anyone tries to use it
    mod_flatten_conditionals.apply(dom_root, "IM_VEC2_CLASS_EXTRA", False)
    mod_flatten_conditionals.apply(dom_root, "IM_VEC4_CLASS_EXTRA", False)
    mod_flatten_namespaces.apply(dom_root, {'ImGui': 'ImGui_'})
    mod_flatten_nested_classes.apply(dom_root)
    # The custom type fudge here is a workaround for how template parameters are expanded
    # Each iteration handles templates one more nesting level deep
    for _ in range(0, 2):
        mod_flatten_templates.apply(dom_root, custom_type_fudges={'const ImFont**': 'ImFont* const*'})

    # We treat certain types as by-value types
    mod_mark_by_value_structs.apply(dom_root, by_value_structs=[
        'ImVec2',
        'ImVec4',
        'ImColor',
        'ImStr',
        'ImRect',
        'ImGuiListClipperRange'
    ])
    mod_mark_internal_members.apply(dom_root)
    mod_flatten_class_functions.apply(dom_root)
    mod_remove_nested_typedefs.apply(dom_root)
    mod_remove_static_fields.apply(dom_root)
    mod_remove_extern_fields.apply(dom_root)
    mod_remove_constexpr.apply(dom_root)
    mod_generate_imstr_helpers.apply(dom_root)
    mod_remove_enum_forward_declarations.apply(dom_root)
    mod_calculate_enum_values.apply(dom_root)
    # Treat enum values ending with _ as internal, and _COUNT as being count values
    mod_mark_special_enum_values.apply(dom_root, internal_suffixes=["_"], count_suffixes=["_COUNT"])
    # Mark enums that end with Flags (or Flags_ for the internal ones) as being flag enums
    mod_mark_flags_enums.apply(dom_root, ["Flags", "Flags_"])

    # These two are special cases because there are now (deprecated) overloads that differ from the main functions
    # only in the type of the callback function. The normal disambiguation system can't handle that, so instead we
    # manually rename the older versions of those functions here.
    mod_rename_function_by_signature.apply(dom_root,
        'ImGui_Combo',  # Function name
        'old_callback',  # Argument to look for to identify this function
        'ImGui_ComboObsolete'  # New name
    )
    mod_rename_function_by_signature.apply(dom_root,
        'ImGui_ListBox',  # Function name
        'old_callback',  # Argument to look for to identify this function
        'ImGui_ListBoxObsolete'  # New name
    )

    if not no_generate_default_arg_functions:
        mod_generate_default_argument_functions.apply(dom_root,
                                                      # We ignore functions that don't get called often because in those
                                                      # cases the default helper doesn't add much value but does clutter
                                                      # up the header file
                                                      functions_to_ignore=[
                                                          # Main
                                                          'ImGui_CreateContext',
                                                          'ImGui_DestroyContext',
                                                          # Demo, Debug, Information
                                                          'ImGui_ShowDemoWindow',
                                                          'ImGui_ShowMetricsWindow',
                                                          'ImGui_ShowDebugLogWindow',
                                                          'ImGui_ShowStackToolWindow',
                                                          'ImGui_ShowAboutWindow',
                                                          'ImGui_ShowStyleEditor',
                                                          # Styles
                                                          'ImGui_StyleColorsDark',
                                                          'ImGui_StyleColorsLight',
                                                          'ImGui_StyleColorsClassic',
                                                          # Windows
                                                          'ImGui_Begin',
                                                          'ImGui_BeginChild',
                                                          'ImGui_BeginChildID',
                                                          'ImGui_SetNextWindowSizeConstraints',
                                                          # Scrolling
                                                          'ImGui_SetScrollHereX',
                                                          'ImGui_SetScrollHereY',
                                                          'ImGui_SetScrollFromPosX',
                                                          'ImGui_SetScrollFromPosY',
                                                          # Parameters stacks
                                                          'ImGui_PushTextWrapPos',
                                                          # Widgets
                                                          'ImGui_ProgressBar',
                                                          'ImGui_ColorPicker4',
                                                          'ImGui_TreePushPtr', # Ensure why core lib has this default to NULL?
                                                          'ImGui_BeginListBox',
                                                          'ImGui_ListBox',
                                                          'ImGui_MenuItemBoolPtr',
                                                          'ImGui_BeginPopupModal',
                                                          'ImGui_OpenPopupOnItemClick',
                                                          'ImGui_TableGetColumnName',
                                                          'ImGui_TableGetColumnFlags',
                                                          'ImGui_TableSetBgColor',
                                                          'ImGui_GetColumnWidth',
                                                          'ImGui_GetColumnOffset',
                                                          'ImGui_BeginTabItem',
                                                          # Misc
                                                          'ImGui_LogToTTY',
                                                          'ImGui_LogToFile',
                                                          'ImGui_LogToClipboard',
                                                          'ImGui_BeginDisabled',
                                                          # Inputs
                                                          'ImGui_IsMousePosValid',
                                                          'ImGui_IsMouseDragging',
                                                          'ImGui_GetMouseDragDelta',
                                                          'ImGui_CaptureKeyboardFromApp',
                                                          'ImGui_CaptureMouseFromApp',
                                                          # Settings
                                                          'ImGui_LoadIniSettingsFromDisk',
                                                          'ImGui_LoadIniSettingsFromMemory',
                                                          'ImGui_SaveIniSettingsToMemory',
                                                          'ImGui_SaveIniSettingsToMemory',
                                                          # Memory Allcators
                                                          'ImGui_SetAllocatorFunctions',
                                                          # Other types
                                                          'ImGuiIO_SetKeyEventNativeDataEx',
                                                          'ImGuiTextFilter_Draw',
                                                          'ImGuiTextFilter_PassFilter',
                                                          'ImGuiTextBuffer_append',
                                                          'ImGuiInputTextCallbackData_InsertChars',
                                                          'ImColor_SetHSV',
                                                          'ImColor_HSV',
                                                          'ImGuiListClipper_Begin',
                                                          # ImDrawList
                                                          # - all 'int num_segments = 0' made explicit
                                                          'ImDrawList_AddCircleFilled',
                                                          'ImDrawList_AddBezierCubic',
                                                          'ImDrawList_AddBezierQuadratic',
                                                          'ImDrawList_PathStroke',
                                                          'ImDrawList_PathArcTo',
                                                          'ImDrawList_PathBezierCubicCurveTo',
                                                          'ImDrawList_PathBezierQuadraticCurveTo',
                                                          'ImDrawList_PathRect',
                                                          'ImDrawList_AddBezierCurve',
                                                          'ImDrawList_PathBezierCurveTo',
                                                          'ImDrawList_PushClipRect',
                                                          # ImFont, ImFontGlyphRangesBuilder
                                                          'ImFontGlyphRangesBuilder_AddText',
                                                          'ImFont_AddRemapChar',
                                                          'ImFont_RenderText',
                                                          # Obsolete functions
                                                          'ImGui_ImageButtonImTextureID',
                                                          'ImGui_ListBoxHeaderInt',
                                                          'ImGui_ListBoxHeader',
                                                          'ImGui_OpenPopupContextItem',
                                                      ],
                                                      function_prefixes_to_ignore=[
                                                          'ImGuiStorage_',
                                                          'ImFontAtlas_'
                                                      ],
                                                      trivial_argument_types=[
                                                          'ImGuiCond'
                                                      ],
                                                      trivial_argument_names=[
                                                          'flags',
                                                          'popup_flags'
                                                      ])
        
    if is_probably_imgui_internal:
        # Some functions in imgui_internal already have the Ex suffix,
        # which wreaks havok on disambiguation
        mod_rename_functions.apply(main_src_root, {
            'ImGui_BeginMenuEx': 'ImGui_BeginMenuWithIcon',
            'ImGui_MenuItemEx': 'ImGui_MenuItemWithIcon',
            'ImGui_BeginTableEx': 'ImGui_BeginTableWithID',
            'ImGui_ButtonEx': 'ImGui_ButtonWithFlags',
            'ImGui_ImageButtonEx': 'ImGui_ImageButtonWithFlags',
            'ImGui_InputTextEx': 'ImGui_InputTextWithHintAndSize',
        })
        
    mod_disambiguate_functions.apply(dom_root,
                                     name_suffix_remaps={
                                         # Some more user-friendly suffixes for certain types
                                         'const char*': 'Str',
                                         'char*': 'Str',
                                         'unsigned int': 'Uint',
                                         'unsigned int*': 'UintPtr',
                                         'ImGuiID': 'ID',
                                         'const void*': 'Ptr',
                                         'void*': 'Ptr'},
                                     # Functions that look like they have name clashes but actually don't
                                     # thanks to preprocessor conditionals
                                     functions_to_ignore=[
                                         "cImFileOpen",
                                         "cImFileClose",
                                         "cImFileGetSize",
                                         "cImFileRead",
                                         "cImFileWrite"],
                                     functions_to_rename_everything=[
                                         "ImGui_CheckboxFlags"  # This makes more sense as IntPtr/UIntPtr variants
                                     ],
                                     type_priorities={
                                     })

    # Do some special-case renaming of functions
    mod_rename_functions.apply(dom_root, {
        # We want the ImGuiCol version of GetColorU32 to be the primary one, but we can't use type_priorities on
        # mod_disambiguate_functions to achieve that because it also has more arguments and thus naturally gets passed
        # over. Rather than introducing yet another layer of knobs to try and control _that_, we just do some
        # after-the-fact renaming here.
        'ImGui_GetColorU32': 'ImGui_GetColorU32ImVec4',
        'ImGui_GetColorU32ImGuiCol': 'ImGui_GetColorU32',
        'ImGui_GetColorU32ImGuiColEx': 'ImGui_GetColorU32Ex',
        # ImGui_IsRectVisible is kinda inobvious as it stands, since the two overrides take the exact same type but
        # interpret it differently. Hence do some renaming to make it clearer.
        'ImGui_IsRectVisible': 'ImGui_IsRectVisibleBySize',
        'ImGui_IsRectVisibleImVec2': 'ImGui_IsRectVisible'
    })

    if generate_exploded_varargs_functions:
        mod_add_exploded_variadic_functions.apply(dom_root, 7, not is_probably_imgui_internal) # 7 arguments feels reasonable? Yes.

    if generate_unformatted_functions:
        mod_add_unformatted_functions.apply(dom_root,
                                            functions_to_ignore=[
                                                'ImGui_Text',
                                                'ImGuiTextBuffer_appendf'
                                            ])
        
    if is_probably_imgui_internal:
        mod_move_types.apply(dom_root,
                             main_src_root,
                             [
                                 'ImVector_const_charPtr',
                                 'ImVector_ImGuiColorMod',
                                 'ImVector_ImGuiContextHook',
                                 'ImVector_ImGuiDockNodeSettings',
                                 'ImVector_ImGuiDockRequest',
                                 'ImVector_ImGuiGroupData',
                                 'ImVector_ImGuiID',
                                 'ImVector_ImGuiInputEvent',
                                 'ImVector_ImGuiItemFlags',
                                 'ImVector_ImGuiKeyRoutingData',
                                 'ImVector_ImGuiListClipperData',
                                 'ImVector_ImGuiListClipperRange',
                                 'ImVector_ImGuiNavTreeNodeData',
                                 'ImVector_ImGuiOldColumnData',
                                 'ImVector_ImGuiOldColumns',
                                 'ImVector_ImGuiPopupData',
                                 'ImVector_ImGuiPtrOrIndex',
                                 'ImVector_ImGuiSettingsHandler',
                                 'ImVector_ImGuiShrinkWidthItem',
                                 'ImVector_ImGuiStackLevelInfo',
                                 'ImVector_ImGuiStyleMod',
                                 'ImVector_ImGuiTabBar',
                                 'ImVector_ImGuiTabItem',
                                 'ImVector_ImGuiTable',
                                 'ImVector_ImGuiTableColumnSortSpecs',
                                 'ImVector_ImGuiTableInstanceData',
                                 'ImVector_ImGuiTableTempData',
                                 'ImVector_ImGuiViewportPPtr',
                                 'ImVector_ImGuiWindowPtr',
                                 'ImVector_ImGuiWindowStackData',
                                 'ImVector_unsigned_char',
                                 # This terribleness is because those two types needs to after
                                 # the definitions of ImVector_ImGuiTable and ImVector_ImGuiTabBar
                                 'ImPool_ImGuiTable',
                                 'ImPool_ImGuiTabBar',
                             ])

    # Make all functions use CIMGUI_API
    mod_make_all_functions_use_imgui_api.apply(dom_root)
    mod_rename_defines.apply(dom_root, {'IMGUI_API': 'CIMGUI_API'})

    mod_forward_declare_structs.apply(dom_root)
    mod_wrap_with_extern_c.apply(main_src_root)  # main_src_root here to avoid wrapping the config headers
    # For now we leave #pragma once intact on the assumption that modern compilers all support it, but if necessary
    # it can be replaced with a traditional #include guard by uncommenting the line below. If you find yourself needing
    # this functionality in a significant way please let me know!
    # mod_remove_pragma_once.apply(dom_root)
    mod_remove_empty_conditionals.apply(dom_root)
    mod_merge_blank_lines.apply(dom_root)
    mod_remove_blank_lines.apply(dom_root)
    mod_align_enum_values.apply(dom_root)
    mod_align_function_names.apply(dom_root)
    mod_align_structure_field_names.apply(dom_root)
    mod_align_comments.apply(dom_root)

    # Exclude some defines that aren't really useful from the metadata
    mod_exclude_defines_from_metadata.apply(dom_root, [
        "IMGUI_IMPL_API",
        "IM_COL32_WHITE",
        "IM_COL32_BLACK",
        "IM_COL32_BLACK_TRANS",
        "ImDrawCallback_ResetRenderState"
    ])

    mod_remove_typedefs.apply(dom_root, [
        "ImBitArrayForNamedKeys" # template with two parameters, not supported
    ])

    dom_root.validate_hierarchy()

    # Test code
    # dom_root.dump()

    # Cases where the varargs list version of a function does not simply have a V added to the name and needs a
    # custom suffix instead
    custom_varargs_list_suffixes = {'appendf': 'v'}

    # Get just the name portion of the source file, to use as the template name
    src_file_name_only = os.path.splitext(os.path.basename(src_file))[0]

    print("Writing output to " + dest_file_no_ext + "[.h/.cpp/.json]")

    # If our output name ends with _internal, then generate a version of it without that on the assumption that
    # this is probably imgui_internal.h and thus we need to know what imgui.h is (likely) called as well.
    if is_probably_imgui_internal:
        dest_file_name_only_no_internal = dest_file_name_only[:-9]
    else:
        dest_file_name_only_no_internal = dest_file_name_only

    # Expansions to be used when processing templates, to insert variables as required
    expansions = {"%IMGUI_INCLUDE_DIR%": imgui_include_dir,
                  "%OUTPUT_HEADER_NAME%": dest_file_name_only + ".h",
                  "%OUTPUT_HEADER_NAME_NO_INTERNAL%": dest_file_name_only_no_internal + ".h"}

    with open(dest_file_no_ext + ".h", "w") as file:
        insert_header_templates(file, template_dir, src_file_name_only, ".h", expansions)

        write_context = code_dom.WriteContext()
        write_context.for_c = True
        main_src_root.write_to_c(file, context=write_context)

    # Generate implementations
    with open(dest_file_no_ext + ".cpp", "w") as file:
        insert_header_templates(file, template_dir, src_file_name_only, ".cpp", expansions)

        gen_struct_converters.generate(dom_root, file, indent=0)

        # Extract custom types from everything we parsed,
        # but generate only for the main header
        imgui_custom_types = utils.get_imgui_custom_types(dom_root)
        gen_function_stubs.generate(main_src_root, file, imgui_custom_types,
                                    indent=0,
                                    custom_varargs_list_suffixes=custom_varargs_list_suffixes)

    # Generate metadata
    with open(dest_file_no_ext + ".json", "w") as file:
        # We intentionally generate JSON starting from the root here so that we include defines from imconfig.h
        gen_metadata.generate(dom_root, file)


if __name__ == '__main__':
    # Parse the C++ header found in src_file, and write a C header to dest_file_no_ext.h, with binding implementation in
    # dest_file_no_ext.cpp. Metadata will be written to dest_file_no_ext.json. implementation_header should point to a
    # file containing the initial header block for the implementation (provided in the templates/ directory).

    print("Dear Bindings: parse Dear ImGui headers, convert to C and output metadata.")

    # Debug code
    #type_comprehender.get_type_description("void (*ImDrawCallback)(const ImDrawList* parent_list, const ImDrawCmd* cmd)").dump(0)

    default_template_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "src", "templates")

    parser = argparse.ArgumentParser(
                        add_help=True,
                        epilog='Result code 0 is returned on success, 1 on conversion failure and 2 on '
                               'parameter errors')
    parser.add_argument('src',
                        help='Path to source header file to process (generally imgui.h)')
    parser.add_argument('-o', '--output',
                        required=True,
                        help='Path to output files (generally cimgui). This should have no extension, '
                             'as <output>.h, <output>.cpp and <output>.json will be written.')
    parser.add_argument('-t', '--templatedir',
                        default=default_template_dir,
                        help='Path to the implementation template directory (default: ./src/templates)')
    parser.add_argument('--nopassingstructsbyvalue',
                        action='store_true',
                        help='Convert any by-value struct arguments to pointers (for other language bindings)')
    parser.add_argument('--nogeneratedefaultargfunctions',
                        action='store_true',
                        help='Do not generate function variants with implied default values')
    parser.add_argument('--generateexplodedvarargsfunctions',
                        action='store_true',
                        help='Generate variants of variadic function with an explicit arguments list '
                             '(for bindings to languages without variadic function support)')
    parser.add_argument('--generateunformattedfunctions',
                        action='store_true',
                        help='Generate unformatted variants of format string supporting functions')
    parser.add_argument('--backend',
                        action='store_true',
                        help='Indicates that the header being processed is a backend header (experimental)')
    parser.add_argument('--imgui-include-dir',
                        default='',
                        help="Path to ImGui headers to use in emitted include files. Should include a trailing slash "
                             "(eg \"Imgui/\"). (default: blank)")
    parser.add_argument('--config-include',
                        help="Path to additional .h file to read configuration defines from (i.e. the file you set "
                             "IMGUI_USER_CONFIG to, if any).",
                        default=[],
                        action='append')

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(0)

    args = parser.parse_args()

    config_include_files = []

    # Add imconfig.h to the include list to get any #defines set in that
    config_include_files.append(os.path.join(os.path.dirname(os.path.realpath(args.src)), "imconfig.h"))

    # Add any user-supplied config file as well
    for config_include in args.config_include:
        config_include_files.append(os.path.realpath(config_include))

    # Perform conversion
    try:
        convert_header(
            os.path.realpath(args.src),
            config_include_files,
            args.output,
            args.templatedir,
            args.nopassingstructsbyvalue,
            args.nogeneratedefaultargfunctions,
            args.generateexplodedvarargsfunctions,
            args.generateunformattedfunctions,
            args.backend,
            args.imgui_include_dir
        )
    except:  # noqa - suppress warning about broad exception clause as it's intentionally broad
        print("Exception during conversion:")
        traceback.print_exc()
        sys.exit(1)

    print("Done")
    sys.exit(0)
