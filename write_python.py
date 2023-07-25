import io
from itertools import chain
from pathlib import Path
from typing import TextIO

import describe


def class_capitalize(ori_str: str) -> str:
    try:
        return ori_str[0].upper() + ori_str[1:]
    except IndexError:
        return ori_str


def resource_class_name(ori_name: str) -> str:
    return f"Resource{class_capitalize(ori_name)}"


class File:
    def __init__(self, discovery_dict: dict) -> None:
        self.classes: dict[str, 'Class'] = {}
        self.imports: list[str] = []

        schemas: dict = discovery_dict['schemas']
        self.add_schemas(schemas)
        del discovery_dict['schemas']

        api_id: str = discovery_dict['id']
        self.add_class(''.join(class_capitalize(i) for i in api_id.split(':')),
                       discovery_dict)
        self.add_resources(discovery_dict['resources'])

        self.file_name = f"{'_'.join(i.lower() for i in api_id.split(':'))}.py"

    def add_class(self, class_name: str, class_dict: dict):
        new_class = Class(class_name, class_dict, self)
        self.classes[class_name] = new_class

    def add_schemas(self, schemas: dict[str, dict]):
        for schema_name, schema_dict in schemas.items():
            self.add_class(schema_name, schema_dict)

    def add_resources(self, resources: dict[str, dict]):
        for resource_name, resource_dict in resources.items():
            self.add_class(resource_class_name(resource_name), resource_dict)


class Class:
    def __init__(self, class_name: str, class_dict: dict, file: File | None = None) -> None:
        self.class_name = class_name
        self.methods: list[Method] = []
        self.class_attributes: list[Attribute] = []
        self.attributes: list[Attribute] = []
        self.class_dependencies: list[str] = []
        self.import_dependencies: list[str] = []
        self.description: str = None

        self.file: File | None = file

        self.load_dict(class_dict)

    def load_dict(self, class_dict: dict):
        for key, value in class_dict.items():
            if key == 'properties':
                self.add_properties(value)
            if key == 'description':
                self.description = value
            if key == 'resources':
                self.add_resources(value)
            if key == 'methods':
                self.add_methods(value)

    def add_attribute(self, name: str, value, comment: str | None = None,
                      type_: str | None = None):
        self.attributes.append(Attribute(name, value, comment, type_))

    def add_class_attribute(self, name: str, value, comment: str | None = None,
                            type_: str | None = None):
        self.class_attributes.append(Attribute(name, value, comment, type_))

    def add_properties(self, properties: dict):
        for name, info in properties.items():
            if 'type' in info:
                type_ = info['type']
            elif '$ref' in info:
                type_ = info['$ref']
                self.class_dependencies.append(type_)
            else:
                type_ = None
            if 'enum' in info:
                enum_class = EnumClass(
                    f"{self.class_name}{class_capitalize(name)}", info)
                self.class_dependencies.append(enum_class.class_name)
                self.file.classes[enum_class.class_name] = enum_class
                type_ = enum_class.class_name
            self.add_class_attribute(name, None, info['description'], type_)

    def add_resources(self, methods: dict[str, dict]):
        for resource_name, resource in methods.items():
            resource_method = Method(resource_name)
            resource_method.return_value = resource_class_name(resource_name)
            self.class_dependencies.append(resource_method.return_value)
            self.methods.append(resource_method)

    def add_methods(self, methods: dict[str, dict]):
        for method_name, method_dict in methods.items():
            method = Method(method_name,
                            description=method_dict['description'])
            method.return_value = self.load_method_response(method_dict)
            method.load_parameters_description(method_dict)
            self.class_dependencies.append(method.return_value)
            method.arguments = self.load_method_arguments(method_dict)
            self.sort_method_arguments(method, method_dict)
            self.methods.append(method)

    @staticmethod
    def sort_method_arguments(method: 'Method', method_dict: dict[str, dict]) -> None:
        try:
            order = method_dict['parameterOrder']
        except KeyError:
            order = []

        method.sort_arguments(order)

    def load_method_arguments(self, method_dict: dict[str, dict]) -> list['MethodArgument']:
        parameters_list = []

        try:
            parameters_dict: dict[str, dict] = method_dict['parameters']
        except KeyError:
            return parameters_list

        for argument_name, argument_dict in parameters_dict.items():
            argument = MethodArgument(argument_name)
            argument.required = argument_dict.get("required", False)
            argument.annotation_type = Attribute.translate_type(argument_dict.get("type",
                                                                                  ""))
            if not self.is_attribute_enum(argument_dict):
                argument.default_value = Class.load_default_value(argument_dict.get("default", ""),
                                                                  argument.annotation_type)
            else:
                enum_class = EnumClass(argument_name, argument_dict)
                self.class_dependencies.append(enum_class.class_name)
                self.file.classes[enum_class.class_name] = enum_class
                argument.annotation_type = enum_class.class_name
                argument.default_value = enum_class.load_default_value(
                    argument_dict)
            parameters_list.append(argument)

        return parameters_list

    @staticmethod
    def is_attribute_enum(argument_dict: dict) -> bool:
        return 'enum' in argument_dict

    @staticmethod
    def load_method_response(method_dict: dict[str, dict]) -> str:
        try:
            method_response = method_dict['response']
        except KeyError:
            return 'None'

        if isinstance(method_response, dict):
            return method_response['$ref']
        elif isinstance(method_response, str):
            return method_response

        raise ValueError

    @staticmethod
    def load_default_value(default_value: str, annotation_type: str) -> str:
        if not default_value:
            return ""

        if annotation_type == 'bool':
            return class_capitalize(default_value)
        if annotation_type == 'int':
            return default_value
        if annotation_type == 'str':
            return f"'{default_value}'"

        raise TypeError


    @staticmethod
    def get_writer():
        return ClassWriter


class EnumClass(Class):
    def __init__(self, argument_name: str, attribute_dict: dict[str, dict], subclass: str = None, file: File | None = None) -> None:
        self.class_name = self.enum_class_name(argument_name)
        self.subclass = subclass
        self.elements: list[EnumClassElement] = []
        Class.__init__(self, self.class_name, attribute_dict, file)

    @staticmethod
    def enum_class_name(argument_name: str) -> str:
        return f"Enum{class_capitalize(argument_name)}"

    def load_dict(self, attribute_dict: dict[str, dict]):
        self.subclass = Attribute.translate_dict[attribute_dict['type']]
        attribute_values = attribute_dict['enum']
        attribute_comments = attribute_dict['enumDescriptions']

        for value, annotation in zip(attribute_values, attribute_comments):
            self.elements.append(EnumClassElement.str_element(value,
                                                              annotation))

    def load_default_value(self, attribute_dict: dict[str, dict]):
        try:
            default_value = attribute_dict['default']
        except KeyError:
            return ""

        for element in self.elements:
            if element.value == default_value:
                return f"{self.class_name}.{element.name}"

        raise ValueError

    @staticmethod
    def get_writer():
        return EnumClassWriter


class EnumClassElement:
    def __init__(self, name: str, value, annotation: str):
        self.name = name
        self.value = value
        self.annotation = annotation

    @classmethod
    def str_element(cls, value: str, annotation: str) -> 'EnumClassElement':
        name = value.upper()
        if name[0].isnumeric():
            name = f"_{name}"
        return EnumClassElement(name, value, annotation)


class Attribute:
    translate_dict = {'string': 'str',
                      'uint32': 'int',
                      'int32': 'int',
                      'integer': 'int',
                      'boolean': 'bool',
                      'array': 'list',
                      'object': 'dict'}

    def __init__(self, name: str, value, annotations: str | None = None, type_: str | None = None) -> None:
        self.name = name
        self.value = value
        if type_ is None:
            self.type = type(self.value).__name__
        else:
            self.type = Attribute.translate_type(type_)
        if isinstance(self.value, str):
            self.value = f'"{self.value}"'
        self.annotations = "" if annotations is None else annotations

    @classmethod
    def translate_type(cls, type_in_json: str) -> str:
        try:
            return cls.translate_dict[type_in_json]
        except KeyError:
            return type_in_json


class Method:
    def __init__(self, name: str, return_value: str | None = None, implementation: str = '...',
                 description: str | None = None) -> None:
        self.name = name
        self.arguments: list[MethodArgument] = []
        self.return_value: str = return_value
        self.implementation: str = implementation
        self.description: str = description

    def sort_arguments(self, arguments_order: list[str]):
        index_arguments = {
            argument.name: argument for argument in self.arguments}

        new_list = []
        for argument in arguments_order:
            new_list.append(index_arguments[argument])
        set_arguments_order = set(arguments_order)
        not_default = (argument for argument in self.arguments
                       if argument.default_value == '')
        default = (argument for argument in self.arguments
                   if argument.default_value != '')
        for argument in chain(not_default, default):
            if argument.name not in set_arguments_order:
                new_list.append(argument)

        self.arguments = new_list

    
    def load_parameters_description(self, method_dict: dict[str, dict]):
        try:
            params_dict = method_dict['parameters']
        except KeyError:
            return

        parameters_description = io.StringIO()
        for param_name, param_dict in params_dict.items():
            try:
                description = param_dict['description']
            except KeyError:
                continue

            parameters_description.write(f"\n\n`{param_name}`: {description}")

        self.description = f"{self.description}{parameters_description.getvalue()}"


class MethodArgument:
    def __init__(self, name: str, default_value=None, annotation_type: str = None, required: bool = True) -> None:
        self.name = name
        self.default_value = default_value
        self.annotation_type = annotation_type
        self.required = required


class Indentation:
    def __init__(self) -> None:
        self.indent = 0
        self.spaces = 4

    def __add__(self, val):
        if not isinstance(val, int):
            raise TypeError
        if self.indent + val < 0:
            raise ValueError
        self.indent += val
        return self

    def __sub__(self, val):
        if not isinstance(val, int):
            raise TypeError
        if self.indent - val < 0:
            raise ValueError
        self.indent -= val
        return self

    def __str__(self) -> str:
        return " " * self.indent * self.spaces


class PythonWriter:
    indentation = Indentation()
    dump_folder = Path("dump_folder")
    dump_folder.mkdir(parents=True, exist_ok=True)

    def __init__(self, output_file: TextIO) -> None:
        self.output_file = output_file

    def write_line(self, content: str | None = None):
        content = "" if content is None else content
        content = f"{self.indentation}{content}".rstrip()
        self.output_file.write(f"{content}\n")


class FileWriter(PythonWriter):
    def __init__(self, file: File) -> None:
        self.python_file_path = self.dump_folder / file.file_name
        PythonWriter.__init__(self, open(self.python_file_path,
                                         mode='w'))
        self.file = file
        self.written_classes: set[str] = set()

    def write_class(self, class_: Class):
        if class_.class_name in self.written_classes:
            return
        self.written_classes.add(class_.class_name)

        for dependency_class in class_.class_dependencies:
            try:
                class_to_write = self.file.classes[dependency_class]
            except KeyError:
                continue
            self.write_class(class_to_write)

        writer_class = class_.get_writer()
        writer_class(class_, self.output_file).write()

    def write(self):
        self.write_includes()
        for class_name, class_ in self.file.classes.items():
            self.write_class(class_)

    def write_includes(self):
        if any(isinstance(class_, EnumClass) for class_ in self.file.classes.values()):
            self.write_line('import enum')
            self.write_line()


class ClassWriter(PythonWriter):
    def __init__(self, class_: Class, output_file: TextIO) -> None:
        PythonWriter.__init__(self, output_file)
        self.class_ = class_

    def write(self):
        self.write_line(f"class {self.class_.class_name}:")
        self.indentation += 1
        self.write_class_description()
        self.write_class_attributes()
        self.write_class_methods()
        self.indentation -= 1
        self.write_line()
        self.write_line()

    def write_class_description(self):
        if self.class_.description is None:
            return

        self.write_line("'''")
        self.write_line(self.class_.description)
        self.write_line("'''")

    def write_class_attributes(self):
        for attribute in self.class_.attributes:
            AttributeWriter(attribute, self.output_file).write()
            self.write_line()
        for attribute in self.class_.class_attributes:
            AttributeWriter(attribute, self.output_file).write()
            self.write_line()

    def write_class_methods(self):
        for method in self.class_.methods:
            MethodWriter(method, self.output_file).write()
            self.write_line()


class AttributeWriter(PythonWriter):
    def __init__(self, attribute: Attribute, output_file: TextIO) -> None:
        PythonWriter.__init__(self, output_file)
        self.attribute = attribute

    def write(self):
        if self.attribute.annotations:
            for sentence in self.attribute.annotations.split('\n'):
                self.write_line(f"# {sentence}")
        assign_value = "" if self.attribute.value is None else f" = {self.attribute.value}"
        self.write_line(f"{self.attribute.name}: {self.attribute.type}"
                        f"{assign_value}")


class MethodArgumentWriter:
    def __init__(self, parameter: MethodArgument) -> None:
        self.parameter = parameter

    def __str__(self) -> str:
        parameter_str = io.StringIO()
        parameter_str.write(self.parameter.name)
        if self.parameter.annotation_type:
            parameter_str.write(f": '{self.parameter.annotation_type}'")
        if self.parameter.default_value:
            parameter_str.write(f" = {self.parameter.default_value}")
        return parameter_str.getvalue()


class MethodArgumentsWriter:
    def __init__(self, parameters: list[MethodArgument]) -> None:
        self.parameters = parameters
        self.static = False

    def __str__(self):
        parameters_str = io.StringIO()
        if not self.static:
            parameters_str.write('self, ')

        parameters_str.write(', '.join(str(MethodArgumentWriter(parameter))
                                       for parameter in self.parameters))

        answer = parameters_str.getvalue()
        answer = answer.strip()
        answer = answer.strip(',')
        return answer


class MethodWriter(PythonWriter):
    def __init__(self, method: Method, output_file: TextIO) -> None:
        PythonWriter.__init__(self, output_file)
        self.method = method

    def write(self):
        self.write_line(self.get_signature())
        self.indentation += 1
        self.write_method_description()
        self.write_line(self.method.implementation)
        self.indentation -= 1

    def get_signature(self) -> str:
        code_line = io.StringIO()
        code_line.write(f"def {self.method.name}")
        code_line.write(f"({MethodArgumentsWriter(self.method.arguments)})")
        code_line.write(f" -> '{self.method.return_value}':")

        return code_line.getvalue()

    def write_method_description(self):
        if self.method.description is None:
            return

        self.write_line("'''")
        for comment_line in self.method.description.split("\n"):
            self.write_line(comment_line)
        self.write_line("'''")


class EnumClassWriter(PythonWriter):
    def __init__(self, enum_class: EnumClass, output_file: TextIO) -> None:
        PythonWriter.__init__(self, output_file)
        self.enum_class = enum_class

    def write(self):
        self.write_line(self.get_signature())
        self.indentation += 1
        for value in self.enum_class.elements:
            self.write_value(value)
        self.indentation -= 1
        self.write_line()
        self.write_line()

    def get_signature(self) -> str:
        code_line = io.StringIO()
        code_line.write(f"class {self.enum_class.class_name}(")
        if self.enum_class.subclass:
            code_line.write(f"{self.enum_class.subclass}, ")
        code_line.write("enum.Enum):")
        return code_line.getvalue()

    def write_value(self, value: EnumClassElement):
        if value.annotation:
            self.write_line(f"# {value.annotation}")
        self.write_line(f"{value.name.upper()} = '{value.value}'")
        self.write_line()


def get_discovery(api_id: str):
    return describe.generate_discovery_api(api_id)


def is_valid_python_file(file_path: Path):
    return is_valid_python(file_path.read_text())


def is_valid_python(code):
    try:
        exec(code)
    except Exception as e:
        return False

    return True


def main():
    a = get_discovery('blogger:v3')
    blogger_file = File(a)
    blogger_file_writer = FileWriter(blogger_file)
    blogger_file_writer.write()
    if not is_valid_python_file(blogger_file_writer.python_file_path):
        print("Code for blogger generated with errors")
    pass
    b = get_discovery('drive:v3')
    drive_file = File(b)
    drive_file_writer = FileWriter(drive_file)
    drive_file_writer.write()
    if not is_valid_python_file(drive_file_writer.python_file_path):
        print("Code for drive generated with errors")


if __name__ == '__main__':
    main()
